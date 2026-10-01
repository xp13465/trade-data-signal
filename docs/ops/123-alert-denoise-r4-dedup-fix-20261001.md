# #123 R4 拦截块 update_dedup 无条件落盘修复(implementer,2026-10-01)

> 任务:续跑 #123 告警降噪,修第二轮复验 FAIL 唯一缺陷——notify.py R4 拦截块 `update_dedup` 无条件执行,不看发送结果。
> 分支:`worktree-agent-af1e103df45f2939c`;base 起于 `origin/main`(rebase 后 base-fresh)。
> 上游审查报告:docs/ops/123-alert-denoise-fix-review-20261001.md §④ 4.3(FINDING,FAIL 依据)。
> 上一轮修复报告:docs/ops/123-alert-denoise-fix-r5-r1-20261001.md(R5/R1 已由审查实测确认修复成立)。

## 结论

- **修复成立(PASS,正反例实测)**:R4 块 `update_dedup` 改为与同文件通用路径 L2157 同构——severe 任一渠道真发出才占 21600s 窗;全渠道失败不更新,下次调用必重试;**info 级只记 dashboard 不推送,渠道全 False 不占窗(同时免 info 占 severe 窗,审查「可选」项顺带达成)**。
- **举一反三(update_dedup 4 处调用点逐处核)**:L747 / L1324 / L2157 三处全部带发送成功判据;L2126(现 L2133 修复)是**全文件唯一**「不检查发送结果就 update_dedup」的点,已修。
- **更广一层核查(同文件其他状态落盘点)**:write_alert / log_info / defer_warning / flush_warning_batch 逐处核,无同类「静默吞真故障」缺陷(逐处结论见 §4)。

## 1 缺陷定位(审查 §④ 4.3 原文要点)

- `scripts/notify.py` R4 拦截块(现 L2106-2136):`if args.dedup_key and not args.dry_run: update_dedup(args.dedup_key)` 无条件执行——不看 `send_tiered` 发送结果、不区分 tier。
- 违背:
  - 同文件通用路径契约(现 L2157-2158:`and ok`)——P1-1(2026-08-11)「发送成功才更新,失败不标记下次可重发」;
  - `update_dedup` docstring(L1231-1236):「发送**成功**后更新……调用方须在确认至少一个渠道发送成功后才调用」。
- 后果链(审查原文):staticdata_backup_async.sh L456-460 调 notify.py `--severe --dedup-key staticdata_backup_fail --dedup-window 3600`(**不带 --alert-issue**,dashboard 无落盘)→ 某轮发送全失败(邮件/飞书/TG 通道故障,P1-1 历史证明真实发生过)→ 仍记 dedup → 6h 窗口内同 key 被 `check_dedup(21600)` suppress 不重试 → 备份每日一轮,6h 后无下一次调用 → **当天备份失败告警完全静默,用户不可见**。这正是「降噪不得吞掉真故障判别维度」红线。

## 2 改动 diff

`scripts/notify.py` R4 块,L2125-2126(修前):

```python
        if args.dedup_key and not args.dry_run:
            update_dedup(args.dedup_key)
        if args.alert_issue:
```

L2125-2132(修后,8 行注释 + 同构判据):

```python
        # P1-1 契约(2026-10-01 R4 补审修复): 发送成功才更新 dedup——severe 任一渠道真发出
        # 才占 21600s 窗(与通用路径 L2150 `and ok` 同构); 全渠道失败不更新, 下次调用可重试
        # (防 staticdata 备份失败告警在发送故障时被静默 suppress 吞掉)。info 级只记 dashboard
        # 不推送, 渠道全 False 不占窗(也不占 severe 窗)。按渠道字段过滤 send_tiered 返回里的
        # 非渠道键(tier/info_logged/deferred), 防 `any(results.values())` 被 info_logged 误判。
        _r4_sent = [ch for ch, v in results.items()
                    if v and ch in ("email", "telegram", "feishu")]
        if args.dedup_key and not args.dry_run and _r4_sent:
            update_dedup(args.dedup_key)
        if args.alert_issue:
```

**为什么不用 `any(results.values())`**(审查建议字面):`send_tiered` 返回 dict 含非渠道键——critical 形态 `{"tier", "email", "telegram", "feishu"}`,info 形态还含 `info_logged: True`、warning 形态含 `deferred: True`。`any(values())` 会被 info 的 `info_logged=True` 误判为「发送成功」→ info 级仍占窗,违背审查「可选:info 不占 severe 窗」且与「发送成功才更新」契约不符。按渠道字段 `("email","telegram","feishu")` 过滤后,与通用路径 `ok = [ch for ch, v in results.items() if v]` 语义一致(send() 返回恰为三渠道)。

## 3 自测证据(正反例,生产隔离)

脚本:`scripts/tests/test_notify_r4_dedup_20261001.py`(monkeypatch `send_tiered`/`r4_staticdata_grade` 桩 + `DEDUP_FILE` 重定向 /tmp,不真发信、不碰生产文件)。判定基于 `data/notify_dedup.json` 真实读写 + `check_dedup` 真实逻辑。

```
========== R4 dedup 修复自测结果 ==========
[PASS] 1.正例 all_ok -> dedup 更新  |  send=1 key=True
[PASS] 2.正例续跑 -> 窗口内 suppress  |  send=0(期望0=suppress)
[PASS] 3.反例 all_fail -> dedup 不更新  |  send=1 key=False(期望无key)
[PASS] 4.反例续跑 -> 失败后下次调用重试  |  send=1(期望1=重试非suppress) key=True
[PASS] 5.info 级 -> 不占窗  |  send=1(info记dashboard) key=False(期望无key)
[PASS] 6.tg_only -> 任一渠道成功占窗  |  send=1 key=True
===========================================
总判定: ALL PASS
```

对照自测映射:
1. **正例**(发送成功 → dedup 照常更新):场景 1,key=True——去重语义不变,不引入告警轰炸。
2. **反例关键**(发送全失败 → dedup 必须不更新 → 下次必重试):场景 3 key=False(不静默);场景 4 立即重跑不被 suppress(send=1 重试,非 return 0)。
3. **审查后果链场景**(staticdata_backup_async 不带 --alert-issue + 全失败 → 6h 内静默):场景 3 的调用**未带 --alert-issue**(与 L457-460 真实调用一致),全失败后 dedup 无 key → 6h 内任何下一次调用(check_dedup 查无此 key 返回 False)必重试 → 静默已消除。场景 2 证明窗口 suppress 仍只对「真发送成功」生效(不轰炸)。
4. **info 不占窗**:场景 5 key=False——顺带达成审查「可选:info 级不 update_dedup(避免 info 占 severe 窗)」。
5. **任一渠道成功即占窗**:场景 6(tg_only)key=True——与通用路径 `ok` 口径一致。

**既有测试回归**:`scripts/tests/test_alert_denoise_20261001.py` 34 项 check 断言全部 PASS,0 FAIL(上一轮 R5/R1 修复未被本次 notify.py 改动破坏)。

## 4 举一反三:逐处清单(§23.3)

### 4.1 `update_dedup(` 全部调用点(4 处,逐处核)

| 调用点 | 场景 | 是否检查发送成功 | 结论 |
|---|---|---|---|
| L747 | feishu 配置缺失告警 | `ok = _send_email(...)` → `if ok and not dry_run` | ✅ OK |
| L1324 | agent-done 完成通知 | `results = send(...)` → `if not dry_run and any(results.values())`(send 返回恰为三渠道) | ✅ OK |
| L2133(原 L2126) | R4 拦截块(staticdata_backup_fail) | 修复前**无条件**;修复后 `_r4_sent = [ch for ch,v in results.items() if v and ch in 三渠道]` | ⚠️ 唯一缺陷 → **本次修** |
| L2157-2158 | 通用路径(P1-1) | `if args.dedup_key and not args.dry_run and ok` | ✅ OK |

结论:R4 块是全文件唯一「不检查发送结果就 update_dedup」的点,已修。

### 4.2 同文件其他「改状态 / 写去重 / 写 alert」落盘点(扩一层)

| 落盘点 | 是否「不检查前置动作就落盘」 | 结论 |
|---|---|---|
| `write_alert` L2078/2136/2161(R4 块与通用路径调用) | 无条件写 dashboard(latest.md) | ✅ OK——语义=「记录告警事件」,与发送是否成功无关;发送失败仍记 dashboard 是**防静默**的正确方向,非吞故障 |
| `log_info` L2011(send_tiered info 分支) | 无条件记 info_log.jsonl | ✅ OK——info 级设计=只记 dashboard 不推送,无「前置发送」概念 |
| `defer_warning` L2014(send_tiered warning 分支)返回值被忽略 | `defer_warning` 返回 `_append_jsonl` 结果但 send_tiered 不回传(`{"deferred": True}`) | ⚠️ 轻微同型(观察,不改):buffer 写失败会向调用方谎报 deferred;但①R4 块只走 critical/info,不触 warning;②defer_warning 失败时内部 print 错误行(非静默);③warning 聚合另有 flush 兜底与 lock;④改返回结构属需求外改动(L11),收益低 |
| `flush_warning_batch` L1894-1898 | `sent = any(results.values())` → `if sent and not dry_run` 才清 buffer+写快照 | ✅ OK——docstring「发送成功才清已发条目(失败留下轮重试)」实现成立 |
| `update_dedup` 本体 L1240-1268 | flock 内读改写,锁内失败 fail-open(宁多勿漏) | ✅ OK——「锁内失败仍 fail-open(不 suppress)」注释明确 |

结论:除已修的 R4 块外,无同类「静默吞真故障」落盘点;唯一轻微同型(defer_warning 返回值忽略)已在表内说明不改理由。

## 复现段

- 修复自测:分支上 `scripts/tests/test_notify_r4_dedup_20261001.py`(6 场景,ALL PASS)。
- 既有回归:分支上 `scripts/tests/test_alert_denoise_20261001.py`(34 check 断言,0 FAIL)。
- 关键代码位:notify.py R4 块 L2106-2136(L2133 = 修复后 update_dedup)/ L2157-2158(通用路径 and ok)/ update_dedup L1230-1269;staticdata_backup_async.sh L456-460(调用方,不带 --alert-issue)。
- 审查独立实测(复验锚点):/tmp/rev123b/(rev_indep_r5.py / rev_indep_r1.py / rev_old_new_compare.py / rev_r5_old_vs_new.py)。
