# 独立审查报告(只读判改):feat/upload-retry-capture-fix-20261117 @ d1dc4af18

> 落地来源: /tmp/review-upload-retry-capture-20261117.md; 落地时间 2026-11-17; 对应被审 commit: d1dc4af18(base 26db7ea79)

- 审查者:reviewer agent(独立上下文)
- 目标:commit `d1dc4af1873c56f5f92c3e1e86b32d00c8cff06c`,base `26db7ea79`
- worktree:`/Users/linhuichen/code/trade/.claude/worktrees/agent-adf470bb5b748779a`
- 审查时点:2026-11-17
- 改动面:`scripts/r2_safe_write.py`(+143)、`scripts/backup_state_capture.py`(+169)、`docs/backup-restore.md`(+18)、`scripts/tests/test_upload_retry_capture_fix_20261117.py`(新增 475)
- 改动分级:B 级(运维写路径逻辑 + 跨文件 + 需回归)→ 全量 A/B/C/D 口径审查

## 总结论:**FAIL**(两处必改)

1. **A2 FAIL**:`commit()` 只在 `st in (412, 409, 403, 400)` 时硬停;其余 4xx(404/405/422/…)落进「未确认 → 重放」分支被重试。实测 HTTP 404 ⇒ **3 次 PUT、退避 2.35s + 7.4s**,报 `write unconfirmed HTTP 404; no fallback`。直接违反任务书硬边界「永久性 4xx(412 除外)⇒ 不重试」,也与源码注释 `r2_safe_write.py:36` 自相矛盾。
2. **测试判别力 FAIL**:`test_own_write_landed_then_412_confirms_own_bytes`(新用例 ⑤)对 412 例外**零判别力**——把例外分支短路成 `if False and ...` 后,全文件仍 **22 passed**,单跑该用例也 passed。原因:`Transport.request` 在 `action=='raise'` 时**先抛、后写**(`test_...py:94-95`),第 2 次 PUT 走的是 `ok` 正常路径,412 分支压根没进。用例注释「先把字节写进假对象, 再抛连接断」与假 transport 实际行为不符;`docs/backup-restore.md` 把它列为已覆盖项(「自己的写入已落地遇 412 只认自己字节」)属**过度声明**。

A1 本身**安全**(证明见下),不构成 FAIL 项。

---

## A1 412 例外是否等于覆盖 / 能否放过别人的写入 —— **安全,不覆盖**

判定对象:`r2_safe_write.py:525-531`

```python
if st in (412, 409, 403, 400):
    if st == 412 and transport_failures and self.confirm(row):
        self.purge(row); return
    ... raise UnsafeWrite(f'conditional write rejected HTTP {st}')
```

**逐字结论**:
1. **它不写任何字节**。该分支只做「读回 + 校验 + purge」,没有任何 PUT/写对象动作 ⇒ **结构上不可能覆盖**别人的写入。
2. **它不可能把别人的字节认成自己的**。`confirm()`(`:316-330`)要求**同时**满足两条:`sha(obj) == row['sha256']` **且** `x-amz-meta-write-id == row['write_id']`(`:323-324`)。`write_id` 是每次 `prepare()` 新生成的 uuid4(`:402`),只写进我们自己那次 PUT 的头部(`:419-420`)。别人写入的对象带的是别人的 write_id ⇒ 双条件必不同时成立 ⇒ `confirm()` 返回 False ⇒ 走 `raise`。
3. **只认 sha 是不够的**,但实现没有只用 sha —— 双条件是本次安全性的关键(文件头注释 `:317` 也写明「不把负读/其他写者的相同 bytes 当成本次成功」)。
4. **进入例外的必要条件**:`transport_failures >= 1`,即前序尝试本身是传输层失败(`:546` 只在失败重放后累加)。首轮即 412 时该值为 0 ⇒ 直接失败、不重试。
5. **自己的写入没落地、对象被别人更新**:`confirm()` 读回的是别人的 shа+别人的 write_id ⇒ False ⇒ 如实失败、对象一个字节不动。
6. **自己的写入落地后又被别人覆盖**:读回同样是别人的 ⇒ False ⇒ 失败、不覆盖。

**实测反例/正例(探针 `/tmp/probe_412_exception.py`,让假 transport 真写对象)**:

| 场景 | 结果 |
|---|---|
| A 自己已落地 + 响应丢失 ⇒ 重试 412 | success,confirmed=True,对象=自己的 `new`,meta=自己的,2 PUT,退避 1.86s |
| B 他人抢先落地 ⇒ 412 | raise `rejected HTTP 412`,对象保持 `concurrent` 未被覆盖 |
| C 自己落地后被他人覆盖 ⇒ 412 | raise,对象保持 `concurrent2` 未被覆盖 |
| D 永久 404 | **raise 但 3 PUT / 退避 [2.35, 7.4]**(见 A2) |
| E 429 | success,2 PUT(429 属可重试,符合预期) |
| F 首轮即 412 | raise,1 PUT,零退避(不进例外) |

补充边界(非本次回归):跨进程续跑场景由 `recover()`(`:343-367`)兜底——对 `state=='unknown'` 重放 PUT(`except Exception: pass`)后再 `confirm()`。本轮未改其语义。

---

## A2 永久 4xx / 耗尽 / 语义不变 / 锁与预算 —— **FAIL(永久 4xx 被重试)**,其余 PASS

- **永久 4xx 不重试:FAIL**。`commit()` 只有 `st in (412, 409, 403, 400)` 硬停(`:525`);404/405/422/451 等既不在硬停集合、又 <500 ⇒ 落到 `:535 confirm()` 失败后进入重放分支(`:538-548`)。实测 404 → 3 次 PUT、`R2_WRITE_RETRY` 日志 attempt=3/exhausted=true、退避 [2.35, 7.4]。**修法**:把 `_permanent_http(st)`(`:50`,已写好但只在 `immutable()` 的读回分支使用 `:300`)接进 `commit()`,例如在 `:535` 前加 `if _permanent_http(st): raise UnsafeWrite(f'write rejected HTTP {st}')`。
  - 危害定级:无数据安全影响(if-match 仍在、仍 rc=1、仍不覆盖),但多打 2 次跨境 PUT + 最多 ~10s 退避,与「永久错误不重试」的明确要求相悖,并让 `:36` 注释与代码不一致。
- **429/408 可重试**:实测 E(429)→ 2 PUT 成功,符合设计(408/429 例外由 `_permanent_http` 定义,但 `commit()` 实际靠「落进重放分支」实现,语义正确、路径意外)。
- **耗尽仍 rc=1 不吞错**:`UnsafeWrite('write unconfirmed HTTP {st}; no fallback')`(`:545`)→ 上游 `_upload_glob` 记失败、脚本非零退出;`row` 保持 `state='unknown'`(`:502`,耗尽路径未改状态)可续跑。PASS。
- **checksum / 内容寻址 / if-match / write_id 语义不变**:`prepare()` 未改条件头(`if-match` 旧 ETag / `if-none-match:'*'`),`sha(payload) != row['sha256']` 前置校验仍在(`:495`);备份键仍内容寻址。PASS。
- **重试不绕过锁**:`commit()` 的生产调用点在 `upload_r2.py:1584`,位于 `_upload_one()` 内,先经 `:1564 _acquire_r2_upload_lock(lock_path_override=key_lock_path(...))` 取**按 key 的互斥锁**(`shared_key` 或受保护键),重试全程持锁。PASS。
- **重试不绕过工作预算**:每次重放前 `_work_budget_check('conditional-write-retry')` + `_work_sleep(retry_wait(attempt))`(`:547-548`);`_work_sleep` 会按剩余预算钳制。备份侧同理 `:313-314`。PASS。
- **multipart**:`payload >= 100MB 且 row['complete'] 未写入且 st != 200` ⇒ 直接 `failed`(`:520-524`),不重放、不新开 upload-id。PASS(组合场景见 D10-5)。

## A3 备份读回「空(404)」vs「别的字节」—— **区分正确;一处中等口径缺口**

- 读回字节**不同** ⇒ `raise UnsafeWrite('backup readback SHA256 mismatch')`(`:306`),**不重试不覆盖**。实测用例 ⑦(删对象 + 篡改读回)只 1 次备份 PUT、零重试日志。
- 读回**为空** ⇒ 重试(`:307-314`);生产形态 `404 + NoSuchKey` 实测重试后成功(用例 ④)。
- **缺口(medium-low)**:若 GET 返回 **404 且 body 为空**,`self.get()` 抛 `GET ...: HTTP 404`,`immutable()` 用 `_permanent_http(404)=True` 直接 `raise`(`:296-301`)⇒ **不重试**。探针 `/tmp/probe_backup_404.py` 实测:`[B 404+空body] {'returned':'raise','err':'GET protected-versions/...: HTTP 404','backup_puts':1,'sleeps':[]}`,而 `[A 404+NoSuchKey]` 重试 3 次。真实 R2/R2 兼容端返回 NoSuchKey XML,故线上概率极低;但与「读回为空 ⇒ 可重试」的意图不完全一致。建议把 GET 的 404 视为「空」而非永久错误(或对 readback 的 404 特判放行)。
- 内容寻址路径上「别的字节」不重试:符合任务书。

## B4 `is_transient_intermediate()` 是否宁窄勿宽 —— **PASS**

实现 `backup_state_capture.py:247-263`:`low.startswith(".receipt-")` 或 `re.search(r"\.tmp(?:[.\-_]|$)", low)`。

- 匹配样例:`.receipt-abc123`、`r.json.tmp.deadbeef`、`x.tmp`、`x.tmp-1`、`x.tmp_1`、`x.TMP`(大小写不敏感)。
- **不**匹配样例:`.r2_index_state.json`、`gc-manifest.json`、`alert_state.json`、`x.tmpl.json`、`.receipt.json`、`my.receipt-x.json`。
- 实证 1:既有 fixture 仓 31 个真实声明 rel 全量过规则 ⇒ **0 个被排除**。
- 实证 2:主检出 `data/` 下 583 个真实文件名全量过规则 ⇒ **0 个命中**。
- `.receipt-*` 唯一来源:`scripts/delivery_evidence.py:242` `mkstemp(prefix=".receipt-")` → `:249 os.link` 成 `<receipt_id>.json` → `:268 unlink`,确为中间态。注意 `docs/codex-reviews/.../capture_d1_metrics.py:119` 用的是 `.d1-receipt-` 前缀,**不**被本规则命中(不误排)。
- 理论误排面:`x.tmp.json`、`x.tmp_old`、`x.tmp.bak` 会被排除;今日真实产物中 **0 命中**,且规则只作用于 basename(不碰目录名),符合「宁窄勿宽」。结论:PASS,无真实状态文件被误排。

## B5 间隔 2s + 总窗口 90s / 不得无限等待 —— **PASS(两处低优先瑕疵)**

- 常量 `RETRY_INTERVAL_SECONDS=2.0`、`RETRY_TOTAL_WINDOW_SECONDS=90.0`(`:118-119`)。
- 有界:`for attempt in range(2)` 最多 2 轮(`:743`);窗口只在**睡之前**检查(`:770`),不打断进行中的一轮 ⇒ **绝不无限等**,但「总耗时可略超 90s」(= 第 1 轮耗时 + 2s + 第 2 轮耗时),窗口实质是「睡眠闸」不是硬截止。
- 窗口耗尽语义明确:`window_exhausted=True`(`:771`)→ manifest `retry_window_exhausted=True`(`:795`)→ `status=inconsistent` / `uploadable=False` / `set_dir=None`,主入口 rc=1。用例 ⑤ 实测 `calls==1`、`sleeps==[]`、`retry_window_exhausted True`。
- 瑕疵 1:`retries += 1`(`:759`)在窗口检查(`:770`)**之前** ⇒ 窗口耗尽、实际只跑 1 轮时 manifest 仍记 `retries=1`(语义应是「重试次数=0」)。
- 瑕疵 2:`changed_total = len(set(changed) | set(vanished))`(`:632`)把 vanished 并进 changed 总数,而 `changed_files` 只列 changed ⇒ 只 vanished 时会出现「changed_files=[] 但 changed_total=1」的截断错觉。建议 `changed_total=len(changed_set)`。

## B6 inconsistent 是否真带文件名(manifest + stdout + stderr)与 20 截断总数 —— **PASS**

- manifest:`changed_files/changed_total/vanished_files/vanished_total/sample_diff/retry_window_exhausted`(`:790-795`)。
- stderr:`STATE_CAPTURE_INCONSISTENT` 单行 JSON(`:797-801`),重试前另有 `STATE_CAPTURE_RETRY`(`:763-769`)带 offender。
- stdout:失败行把上述字段逐键拷入唯一 JSON 行(`:1049-1055`)。
- 截断:`MAX_REPORTED_CHANGES=20`(`:120`),`_sample_diff` 各桶截断并带 `*_total`(`:723-725`);`diagnosis` 的 `changed`/`vanished` 也按 20 截断(`:631-634`)。用例 ⑥ 实测主入口 rc=1、唯一 stdout 行含 `changed_files=["alert_state.json"]`。
- 注意:`changed_total` 语义瑕疵同 B5-瑕疵 2。

## C7 自己重跑 + 判别力实检 —— **重跑 PASS,判别力 1 处 FAIL**

重跑(本机,`/Users/linhuichen/code/trade/.venv/bin/python`):
```
python -m pytest -q scripts/tests/test_upload_retry_capture_fix_20261117.py \
  scripts/tests/test_r2_protected_writes_20261111.py scripts/tests/test_backup_state_capture.py
122 passed in 10.92s        # 与实施方报告的 "122 passed in 11.07s" 同量级
```
受影响既有测试(含 `test_345_backup_followups_20261029` / `test_codex_r2_pending_handoff_20261106` / `test_nav_autorecover_20261114` / `test_release_ci_gate`):`262 passed, 13 subtests passed in 51.72s`。

判别力实验(每次改完立即 `git checkout -- <file>`;结束 `git status --porcelain` 为空,`git diff --stat` 为空):

| 实验 | 改动 | 结果 | 结论 |
|---|---|---|---|
| 1 | `TRANSPORT_RETRIES = 2 → 0` | **4 failed, 18 passed**(①第1断次成/②持续断/④读回404/⑤) | 与实施方「拿掉重试 4 红」吻合 |
| 2 | `is_transient_intermediate` 恒 False | **5 failed**(③中间件 + 参数化 4 例) | 「拿掉瞬态排除 5 红」吻合 |
| 3 | **412 例外短路 `if False and ...`** | **22 passed(0 红)**;单跑用例 ⑤ 也 **1 passed** | **零判别力 —— 用例⑤名不副实** |

实施方报告「拿掉捕获三项 ⇒ 5 红」:我按单条拆开验,瞬态排除一项即 5 红(其粒度描述把三项合并计数,数值巧合但方向可复现);有界间隔一项此前实测 1 红。可部分复验通过。

## C8 用例是否真材实料(真实路径/真实函数/不跑生产脚本/无 today) —— **PASS**

- 上传侧:用 `ast` 读**真实** `scripts/upload_r2.py`、仅剥离 `load_env()`/`reconfigure()` 两个模块级调用后 exec(`test_...py:119-125`),只在 fake `HTTPSConnection` 层打桩(`:146`),不触网;`REPO/GIT_REPO` 指 tmp_path,`notify` 打桩,`purge_cache`/`_prune_pre_upload`/`_notify_channel_upload_fail` 打桩。
- 捕获侧:复用既有 `test_backup_state_capture.make_repo` 同款完整声明仓样例(不复制清单),额外投放件写进 tmp 仓;mtime 固定 `FIXTURE_MTIME`。
- 无 `date.today()`/`now()` 断言;`grep today\(|now\(` 在测试文件为 0。TZ=Pacific/Kiritimati、UTC、America/Adak 三时区各跑一次均 22 passed(此前实测)。
- 断言基于真实函数返回(`capture()`/`main()`/`confirm` 状态、manifest 字段),非伪造样本;但用例 ⑤ 的断言张冠李戴(实为 200 路径)→ 归 C7 FAIL,不归 C8。

## C9 全量 pytest 可信度 —— **PASS**

- `/tmp/full-pytest-20261117-final.log`:mtime **2026-11-17 02:37:21**,文件 79 行,汇总行在第 76 行原样 `5405 passed, 6 skipped, 176 subtests passed in 713.58s (0:11:53)`。
- commit 时间 **2026-11-17 03:02:00** ⇒ 日志早于提交 25 分钟,**确为提交前跑**。
- 全文 `grep -c "failed"` = **0**,看不到「删 failed 计数」痕迹(L56);汇总行与实施方报告逐字一致。

---

## D10 边界差集(我先自己推,再对账)

**实施方报告第五节只有「残留声明」(后台任务/未写路径/未改逻辑/待主控 merge),没有边界清单** ⇒ 对账的另一侧为空,我这份清单**全部条目都属差集**,逐条处置如下。

| # | 边界 | 我的结论 | 处置 |
|---|---|---|---|
| 1 | 并发写入:412 例外是否放过他人写入 | 安全(sha+write_id 双条件;探针 B/C 不覆盖) | 已测(探针)+ 已写证明 |
| 2 | 首轮即 412(非传输失败) | `transport_failures=0` ⇒ 不进例外,1 PUT | 已测(探针 F / 用例③) |
| 3 | 永久 4xx 除 412 | **被重试(404 实测 3 PUT)** | **必改**(A2) |
| 4 | 429/408 | 可重试,语义正确 | 已测(探针 E) |
| 5 | multipart 与重试组合 | 显式 guard 在 `complete` 未写入时直接失败;但 `complete` 已写入且对象未落地时会**新开 upload-id 重放**,无测试覆盖。风险=孤儿分片,不影响对象内容正确性 | **声明不测+理由**:100MB+ 路径本轮无变更;row['complete'] 已写说明 complete 已发出,此时对象多半已落地、confirm 会成功;孤儿分片由既有 lifecycle 清理 |
| 6 | 重试 × 按 key 锁 | 重试全程持锁(`upload_r2.py:1564→1584`),不绕过 | 已验证(代码路径);锁持有时长最坏 +~10s,**观察项**:合并后看云上 upload 总时长 |
| 7 | 重试 × 工作预算 | 每次重放前 `_work_budget_check('conditional-write-retry')` + `_work_sleep` 钳制 | 已验证(代码路径) |
| 8 | 409/403/400 | 硬停不重试 | 已测(用例⑥ 403) |
| 9 | 备份读回 404 空 body | 被当永久错误不重试(与「空即可重试」意图不完全一致) | **上报**(中等),建议特判 readback 404 放行 |
| 10 | 备份读回「别的字节」 | 立即 UnsafeWrite,不重试不覆盖 | 已测(用例⑦) |
| 11 | 捕获集合误排除真实状态文件 | 31 真实 rel + 583 真实文件名 0 命中;`.receipt-` 唯一来源 mkstemp | 已测(实证)+ 不测外样本说明 |
| 12 | 日志格式被下游解析(R2_WRITE_RETRY/STATE_CAPTURE_*) | 无机器解析方(见 D11) | 已验证(grep) |
| 13 | 文档口径 2s/90s/20 与实现一致 | 数字一致;无「已根治」;但把未覆盖的 412 场景写成已覆盖 | **必改**(随 C7 一并) |
| 14 | 既有测试假设 | 6 个受牵连文件 262 passed / 13 subtests | 已跑 |
| 15 | 时敏(隔天绿) | 无 today()/now();三时区各 22 passed | 已跑 |
| 16 | 前端/版本串/SW(§24) | 零前端文件改动 | 不适用 |
| 17 | purge 顺序 | 仍 confirm → purge,412 例外分支亦先 confirm 再 purge;`pending_purge` 在 `:502` 已置真 | 已验证 |
| 18 | `recover()` 与新增重试交互 | 耗尽后 row 保持 unknown(可续跑);recover 仍单次 PUT+有界 confirm(既有行为,本轮未改) | 声明不测+理由(非本次改动面) |
| 19 | 重试导致重复 purge / 重复 record publication | 只在 confirm 成功后 purge 一次;`_record_confirmed_publication` 在 `commit` 之后调用一次 | 已验证 |

## D11 调用方/消费者影响面

- `SafeWriter` 生产调用方:`upload_r2.py:1358`(另有保护写路径)、`:1527`(构造)、`:1584`(`commit`,锁内)、`:2166`(`load` 续跑)、`:5508`(`get` 只读)。无其他模块直接调 `commit/immutable`(其余 `.commit()` 命中均为 sqlite,已排除)。
- `STATE_CAPTURE_*` stdout 消费者:`scripts/backup_db.sh:138-158` 只用 **ready-file**(`:144-145`)与 **rc**(`:142`),**不解析 stdout JSON**;详情靠 `>> "$LOG" 2>&1` 落日志给人工看 ⇒ 新增字段纯增量,不破坏任何解析。
- 旧 `UnsafeWrite` 文案依赖:全仓 grep 无按文案匹配的分支;`upload_r2.py` 只向上抛/记日志。
- `R2_WRITE_RETRY`/`R2_PHASE`:除 `docs/codex-reviews/.../r2.md` 文字说明外无解析方。

## D12 文档一致性

- 数字:`docs/backup-restore.md` 写「正的 2 秒」「90 秒总窗口」「最多 20 条」,与 `:118-120` 一致。
- 「宁窄勿宽」段与实现一致(列出 `.receipt-*`、`*.tmp[.\-_]`/`*.tmp`,并明示不排 `.r2_*_state.json`、`gc-manifest.json` 等)。
- 无「已根治」类过头话。
- **唯一不符**:文档把「自己的写入已落地遇 412 只认自己字节」列为该测试文件的覆盖项,但该用例实测零判别力(C7-实验 3)⇒ 需么改用例真覆盖、么删该条声明。

---

## 合并资格

**不可合并**。必改两项(都很小、局部):
1. `r2_safe_write.py` `commit()`:把 `_permanent_http(st)` 接进去(在 `:535` 前硬停),使 404/405/422 等不重试,与 `:36` 注释一致。
2. 让用例 ⑤ 真进 412 例外:给 `Transport.request` 加「先 `self.put(...)` 落字节、再 `raise OSError`」的动作(如 `landed_raise`),并断言 `confirm()` 的 write_id 命中路径;否则删除 `docs/backup-restore.md` 中该覆盖声明。
另建议(不阻断):A3 的 readback 404 空 body 特判;B5 `retries` 计数在窗口检查后再加;`changed_total` 只用 changed 集合。

## 残留声明

- 残留后台任务:**无**(全程未出现 `moved to the background (ID:`)。
- 为判别力共临时改生产文件 3 次(TRANSPORT_RETRIES、412 例外、瞬态排除),每次均 `git checkout --` 恢复;最终 `git status --porcelain` **为空**、`git diff --stat` **为空**(证据见本次会话第 3/4 次命令输出)。
- 未碰云上、未发任何通知、未 push/merge、未写 `/Users/linhuichen/.claude/`、未碰 worktree 内 `.claude/` 路径。
- 探针文件只落在 `/tmp`:`/tmp/probe_412_exception.py`、`/tmp/probe_backup_404.py`、`/tmp/probe_transient_names.py`。
