# 复审报告(第二轮,只读判改):61d8b6f6c

> 落地来源: /tmp/review-upload-retry-capture-round2.md; 落地时间 2026-11-17; 对应被审 commit: 61d8b6f6c

- 目标:commit `61d8b6f6c1fb83302ba34b677c9afeb4223421de`(父 = 已审 `d1dc4af18`)
- 分支/工作区:`feat/upload-retry-capture-fix-20261117` / `/Users/linhuichen/code/trade/.claude/worktrees/agent-adf470bb5b748779a`
- 改动面:4 文件 +145/−16(`r2_safe_write.py` +18/−、`backup_state_capture.py` +10/−、`docs/backup-restore.md` +9/−、测试 +124)
- 范围:仅复验上一轮 FAIL 四条 + 回归,不重跑全量初查

## 总结论:**PASS(可合并)**

- A 三项判别力实测:①**1 红** ②**3 红** ③**1 红**,与实施方声称完全一致。
- B 四条修法逐条到位;critical 风险点(404 特判误放「非空不同字节」)已排除。
- C 定向 130 passed / 受牵连 292 passed + 13 subtests;全量日志 5413 passed、0 failed、早于 commit。
- D 上一轮差集 ③⑨⑬ 全部关闭;新边界 6 条逐条排查,无回归。

---

## A 判别力实测(每项改完立即 `git checkout --`,结束工作区空)

| 项 | 临时改动 | 实测 | 声称 | 判定 |
|---|---|---|---|---|
| ① | `r2_safe_write.py` 412 例外短路 `if False and ...` | **1 failed, 29 passed**(唯一红 = `test_own_write_landed_then_412_confirms_own_bytes`) | 1 红 | 一致 |
| ② | 删掉 `if _permanent_http(st):` 整段 | **3 failed**(`test_other_permanent_4xx_stops_after_one_put[404/405/422]`) | 3 红 | 一致 |
| ③ | 把 404 特判回退成 `if m and _permanent_http(int(m.group(1))): raise` | **1 failed**(`test_backup_readback_404_empty_body_is_retried`) | 1 红 | 一致 |

补充观察(非缺陷):⑪他人覆盖用例在短路 412 例外时**仍绿**——因为它的期望就是「失败且不覆盖」,两条代码路径都满足,故它检验的是「不覆盖他人」而非「例外分支本身」。真正锁住例外分支的是 ⑤,已实测有效。

## B 四条修法逐条核

### B1 永久 4xx —— 到位
`r2_safe_write.py:541-546`:在 `(412,409,403,400)` 硬停分支之后、`confirm()` 之前插入 `if _permanent_http(st): state=failed; raise UnsafeWrite(f'write rejected HTTP {st}')`。
- `_permanent_http`(:50)= `400<=st<500 and st not in (408,429)` ⇒ 404/405/422/401/402/426 全部 1 次 PUT 后失败;408/429 落到 confirm→重放。
- 412 例外保留在**前面**的分支(:529),顺序上先于 `_permanent_http`,互不影响;实验①②只各自命中自己的用例,交叉无污染 = 无耦合证据。
- 5xx / st==0 仍走重放;耗尽仍 `write unconfirmed HTTP {st}; no fallback`(:545 不变)。
- 实测:⑧参数化 3 例全绿且断言 `len(public_put_calls)==1`、对象保持旧字节、`status` 落盘;⑨408/429 各 2 次 PUT 成功。

### B2 用例⑤假覆盖 —— 已真覆盖
`test_...py:103-106` 新增 `landed_raise`:`self.put(bucket,key,body,headers)` **先落字节**(带自己的 `x-amz-meta-write-id`)再 `raise OSError`。用例⑤(:257-276)改用它。
- 路径确认:attempt1 落字节+抛错→transport_failures=1;`strip_write_id_gets=2` 让首轮 confirm 读不到 write-id;attempt2 因 if-match 指旧 ETag 得 412→进例外→confirm 读到自己的 sha+write_id→成功。
- 实验①:短路例外 ⇒ ⑤ 红 ⇒ **该用例确实锁住了例外分支**。
- ⑪(:355-368)用 `intruder_before_put` 在重试 PUT 前落他人字节+`x-amz-meta-write-id: someone-else` ⇒ 断言 412、2 次 PUT、对象保持 `concurrent`。**不覆盖他人**被锁住。

### B3 备份读回 404 空 body —— 到位,且未误放「非空不同字节」
`r2_safe_write.py:297-307`:GET 抛错时解析 HTTP code,`404 → error_kind='readback_empty'`(可重试);其余 `_permanent_http` 仍 `raise`。
- 关键安全点已核:`get()`(:260-274)只有 `st==404 and b'NoSuchKey' in body` 才返回 None,`st!=200` 一律 raise;200 才返回 `(body, etag, headers)`。因此 **`actual is not None` 只可能来自 200 真对象**,「非空但不同字节」仍走 `:302-306` 的 `raise backup readback SHA256 mismatch`,**不进重试**。
- 用例⑦(corrupt_backup,200+不同字节)实测绿且断言 `retry_logs == []`、只 1 次备份 PUT ⇒ 未被 404 特判带偏。
- 用例⑩(404+空 body 两次)实测绿,日志 `[readback_empty, readback_empty]`。
- 残留(非阻断、pre-existing):200 但 ETag 非法/长度不符 → get 抛无 HTTP code 的 UnsafeWrite ⇒ 归 readback_error 仍可重试(有界 3 次,不覆盖)。

### B4 诊断计数 —— 到位
- `retries` 后移(`backup_state_capture.py:774`):只在窗口检查通过、真进入下一轮时自增。窗口耗尽时 `retries=0`,且 `STATE_CAPTURE_RETRY` 在窗口检查**之前**打印(:763),offender 清单照常进日志 ⇒ **不会因 retries=0 丢失诊断**;另有 `retry_window_exhausted=True` 显式区分「没重试是因为窗口不够」。用例⑤新增断言 `m["retries"]==0`。
- `changed_total` 只计 changed(`:634`),用例⑦(vanished-only)断言 `changed_files==[] && changed_total==0 && vanished_files==["alert_state.json"]`。
- `SourceChanged` 哨兵改 `None`(:330-331):只有显式传 `[]` 才表示「这一类没有」;`read_stable`/读循环仍传默认 None ⇒ 行为不变。

## C 回归

- 定向三文件:`130 passed in 11.52s`(上一轮 122 + 新增 8 例)。
- 受牵连 6 个既有文件 + 新文件:`292 passed, 13 subtests passed in 52.33s`。
- `/tmp/full-pytest-fix-review-fail.log`:mtime **03:55:02**,commit **03:56:05** ⇒ 早于 commit 63 秒,确为提交前跑;第 76/79 行原样 `5413 passed, 6 skipped, 176 subtests passed in 712.53s (0:11:52)`;`grep -c failed` = **0**(L56 无删计数迹象);5413 = 上一轮 5405 + 新增 8 例,数量自洽。

## D 边界差集更新

上一轮 19 条差集里,本轮关闭 3 条:
- **③ 永久 4xx 被重试 → 关闭**:`:541-546` 接入 `_permanent_http`,实验② 3 红、⑧ 3 例绿。
- **⑨ readback 404 空 body 不重试 → 关闭**:`:297-307` 特判,实验③ 1 红、⑩ 绿。
- **⑬ 文档把未覆盖的 412 场景写成已覆盖 → 关闭**:用例⑤ 真覆盖(实验① 1 红),文档声明由虚转实。

其余 16 条结论不变(见第一轮报告 `/tmp/review-upload-retry-capture-20261117.md`)。

**本轮新代码引入的新边界(独立再推,6 条,全部排查)**:
| # | 新边界 | 结论/处置 |
|---|---|---|
| N1 | 412 例外与 `_permanent_http` 判断顺序是否互相影响 | 无:412 在前(:525-534),`_permanent_http` 在后(:541);实验①②互不串红 = 实证无耦合 |
| N2 | 404 特判会不会把「非空不同字节」放成可重试 | 不会:`get()` 非 200 一律 raise,200 才返回字节;不同字节走 `:302-306` 立即抛。用例⑦实证 |
| N3 | 404 特判对 GET 403/401 等的边界 | 仅 `code==404` 特判,其余 `_permanent_http` 仍抛;未扩大放行面 |
| N4 | `_permanent_http` 覆盖面(401/402/426 也被判永久) | 符合「永久 4xx 不重试」规范口径,无副作用 |
| N5 | `retries=0` 是否削弱诊断 | 不削弱:STATE_CAPTURE_RETRY 在窗口检查前打印 + `retry_window_exhausted` 显式标记 |
| N6 | `SourceChanged(changed=[])` 对既有调用方 | 仅 finalize 显式传列表;`read_stable`/读循环传 None 行为不变;`diagnosis` 只做切片 |
| N7 | 新 fake `intruder_before_put` 是否污染其它用例 | 只在⑪赋值,默认 None 不触发;全文件 30 例全绿佐证 |

## 是否可合并

**可合并**。上一轮两条必改均已真修复且有判别力实证;无新增阻塞项。建议 merge 后按既有观察锚点看一次云上 upload 总时长(重试拉长持锁的观察项不变)。

## 残留声明

- 残留后台任务:**无**(未出现 `moved to the background (ID:`)。
- 为判别力临时改生产文件 3 次(`r2_safe_write.py`),每次 `git checkout --` 恢复;终检 `git status --porcelain` 空、`git diff --stat` 空。
- 未碰云上、未发通知、未 push/merge、未写 `~/.claude/`、未碰 worktree 内 `.claude/`。
