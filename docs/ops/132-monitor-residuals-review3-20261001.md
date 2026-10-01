# #132 复审修复(第三轮)独立审查报告 — PASS-with-caveat

分支: `feat/132-monitor-fixups-20261001` | commit: `8c7601885` | 审查: reviewer(独立复现,未改代码)
审查基线: 从 8c7601885 起(reviewer 本报告落 `feat/132-review3-20261001`);复现环境: `git archive 8c7601885` 导出 /tmp/rev132c 隔离运行(不碰生产 data/buffer/lock)
审查对象: 对二轮复审(判 FAIL)的 P0「warning 档 buffer 写失败假成功占窗吞真告警」修复——defer_warning 三态返回。

## 结论: PASS-with-caveat

二轮复审判的 **P0 已真修好**(独立实测:append_failed 绝不占窗、绝不登记指纹,恢复后真入队;修复未引入新 P0)。三态返回的向后兼容已全量核验(**是**,无消费点被改坏)。suppressed 蕴含「之前已真入队」(**是**,append_failed 不会落进内层指纹窗死链)。附带两条 caveat(均为非阻断项):P3 文案的 stderr 文本匹配脆耦合、CLI tier 分支恒 exit 0 的既有设计。**可 merge**。

---

## 1.【最高优先·向后兼容】三态全 truthy 兼容策略覆盖全部消费点 — 是,无点被改坏

### 1.1 修复前 defer_warning 返回类型与取值(独立查证,非照信自述)
- 修复前 `fd3bbdaa3` 版:`-> bool`,函数内全部 `return True`(恒 True)。
- 最早引入版 `9e1dae802`(告警三级分级):`-> bool`,仅 `return True`。
- **「rc=1/rc=2」注释证伪**:`scripts/test_notify_dedup.py` L185「抑制，rc=2」、L199「新源登记 rc=1」、L201「复发 rc=1」——这些注释描述的是**内部指纹窗的 repeat_count 计数**(B1 指纹降噪引入即如此),**不是 defer_warning 返回值编码**。历史上 defer_warning 从未返回过 rc 数值。修复方「旧返回值恒 True」自述属实。

### 1.2 全仓 defer_warning( 调用点逐个消费方式
| 调用点 | 消费方式 | 修复后兼容 |
|---|---|---|
| `notify.py` `send_tiered` L2045 | 消费三态字符串 | 本次修复方,✓ |
| `test_notify_dedup.py` L109-112 | `assertTrue(r1 and r2 and r3)`(truthy) | ✓(全 truthy) |
| `test_notify_dedup.py` L308-309 | `r=...; assertTrue(r)`(truthy) | ✓(append_failed truthy) |
| `test_notify_dedup.py` L125/133/143/152/167/173/175/184/185/193/199/214/222/299/315/368/369/381/382/392/393/407/408/416/436 | 丢弃 | ✓ |
| `test_notify_flush_race.py` L100 | 丢弃 | ✓ |

grep 全仓:**无** `is True` / `== True` / `== 1` / `== 2` / `not r` / `int(r)` / 当退出码返回给 shell 的消费点。test 里 `rc` 均为 repeat_count 局部变量(L339-340),与 defer_warning 返回值无关。
**结论:三态全 truthy 覆盖全部消费点,无点被悄悄改坏。**

### 1.3 CLI 退出码:修复前后无变化
- `--tier warning` 走 main() tier 分支,L2149 无条件 `return 0`(任何 defer_status,含 append_failed),修复前后一致。
- 生产调用方均**不检查 notify 退出码**:`with_lock.py` L128 `subprocess.run(...)` 丢弃结果、`staticdata_sync.sh` L248 末尾 `|| true`、`staticdata_backup_async.sh` L394 末尾 `|| true`。→ rc 无行为变化,无影响。

---

## 2.【深坑验证】append_failed → 内层 4h 指纹窗 → suppress 死链 — 不存在,是

### 2.1 代码链路(独立读码)
- `defer_warning` 抑制分支(L1713-1734)只在 `rec` 已存在且 `_dedup_window_active(rec, now)` 时进入;`rec` 存在的前提 = 此前**成功入队过**(追加失败绝不登记状态,L1751-1754)。
- 追加失败路径:`_append_jsonl` 失败 → `return "append_failed"`,`state[fp] = rec` 未执行(L1755 在 append 成功之后)→ 指纹状态零改动。
- 窗口过期重建路径:旧 rec 窗口过期走 else 重建(L1735-1747),append 失败也不落新 rec → 下次仍重建、仍尝试入队,**不进入抑制分支**。

### 2.2 独立实测(阶段C,真实 CLI,非 mock)
`warning_buffer.jsonl` 建成目录强制 append 失败,同 subject/body(同指纹)连续两次调用:
```
C1 第一次失败后 指纹状态 keys= []   (期望空: 追加失败绝不登记)
C2 第二次同指纹失败后 指纹状态 keys= []  (期望空: 不登记)
C3 notify_dedup.json= {}  (期望空: 全程不占窗)
```
**证实:append_failed 后内层指纹窗无该指纹记录,第二次不会被 suppressed 吞。消息不会「永远收不到」。**

---

## 3. append_failed 不占窗 → 下轮真能重试 — 实测证实

独立实测(阶段A/B,真实 CLI):
```
A1 buffer 目录 append 失败 → defer_status='append_failed', notify_dedup.json={}  (不占窗)
A2 同 key 窗口内第二次(仍 append 失败) → notify_dedup.json 仍 {}  (不占窗,第二次仍进入 defer_warning 重试)
B1 恢复 buffer 为正常文件 → 同 key 真入队(enqueued), buffer=1 条, notify_dedup.json 含 rev3_key (真入队占窗), 指纹已登记
B2 窗口内再调 → 被 main 层 check_dedup suppress(调用方要的 dedup 语义), buffer 仍 1 条
```
四态返回值独立实测(D 段):`enqueued` / `suppressed` / `append_failed` / `dry_run` 全部正确;`send_tiered(dry_run)` → `defer_status='dry_run'`, `deferred=False`。

---

## 4. P1 三段时序 — 剩余抑制全落在设计语义内,dedup 未弱化

独立复现(与 test_p1_fail_then_recover_then_fail_timing 断言一致):
- 段1 append 失败 → 不占窗(notify_dedup.json 无 key)
- 段2 恢复 → 真入队 → 占窗(update_dedup)
- 段3 窗口内再失败 → main 层 check_dedup suppress(段2 消息已真入队/真送达)

**占窗只发生在真入队/真抑制;窗口内二次抑制 = 调用方自选 dedup 语义(自己传的 --dedup-window),不算吞告警。** 对照二轮复审 FAIL 的假成功占窗(消息既没进 buffer 又占窗),本轮已消除。

---

## 5. `_tier_send_ok` critical / info 两档未被带坏

diff 仅改 warning 档:
- critical: `any(res.get(ch) for ch in ("email","telegram","feishu"))` — 未变,真实渠道发出才占窗。
- info: `bool(res.get("info_logged"))` — 未变,记 dashboard 即占窗。
- warning: `res.get("defer_status") in ("enqueued","suppressed")` — 修复核心,append_failed 绝不占窗。
- 兼容:defer_status 缺失时 `None in (...)` → False,与旧 `bool(res.get("deferred"))` 缺失语义一致(都不占窗)。
- `send_tiered` 返回新增 `defer_status` 键不影响 r4 分支的 `_r4_sent` 过滤(L2200 限定 email/telegram/feishu)。

---

## 6. 回归全量(独立重跑,非信修复方数字)

| 测试 | 结果 | 说明 |
|---|---|---|
| `test_132_notify_tier_dedup.py` | 13 OK | 独立跑,含 P0/P1 新用例 |
| `test_notify_dedup.py` | 15 OK | 独立跑 |
| `test_notify_flush_race.py` | 6 OK | 独立跑 |
| `tests/test_132_count_file_fail_loud.py` | 11 PASS | trade-data venv 跑 |
| `tests/test_132_morning_slot.py` | 9 PASS | trade-data venv 跑 |
| `tests/test_132_self_heal_mutex.py` | 全部 PASS | 独立跑 |
| `tests/test_notify_r4_dedup_20261001.py` | 6 PASS | 修正硬编码 worktree 路径后独立跑(r4 契约未受影响) |

**patch-id 比对**:8c7601885 的 notify.py diff 仅 8 个 hunk,全部落在 `defer_warning`(L1633-1774)/`send_tiered` warning 分支(L2039-2051)/`_tier_send_ok`(L2056-2074)。**通用路径 L2208-2228(check_dedup + send + `and ok` + update_dedup)未出现在 diff → 契约未触碰。** 独立验证当前通用路径内容完整。

---

## 7. 新静默路径扫描 — 无新静默

- `defer_warning` L1766-1768:临界区异常补入队的 `except` 从旧 `pass`(静默吞)改为 `appended = False` → 明确进入 append_failed → **改善**非引入。
- `send_tiered` warning 分支:三态返回无 except/提前退出吞异常。
- `_tier_send_ok`:无 except。
- `retry_failed_metrics.py` L113-118:notify 命令非零退出仅 print+return,但**主链路 `main()` L288-291 在 `_save_counts` 写失败时 `return 1`(fail-loud 非零退出)**,notify 发送失败不阻塞该非零兜底(self_heal `||` 分支接管)。非静默。

---

## 8. P3 文案 — 与 notify 实际行为一致(独立实测三态 stderr)

`retry_failed_metrics.py` `_notify_count_file_write_fail` L117-125 按 notify.py stderr 文本区分三态,独立实测:
| notify 场景 | notify stderr 特征串 | P3 打印 | 匹配 |
|---|---|---|---|
| 正常入队 | `入聚合 buffer` | 已入聚合队列(30min 批发, dedup 6h) | ✓ |
| 同 key 窗口内 | `dedup 窗口内 suppress` | 已被 dedup 抑制(6h 窗内已处理过) | ✓ |
| buffer 写失败 | `buffer 追加失败` | buffer 追加失败(未入队、未占窗, 下轮重试) | ✓ |

三处 defer_warning append 失败文案(L1702/L1752/L1772)均含「buffer 追加失败」特征串,P3 全命中。**suppress 时不再打「已发」。**

---

## 问题清单(分级)

| 级 | 问题 | 证据 | 建议 |
|---|---|---|---|
| caveat | P3 文案脆耦合:`retry_failed_metrics.py` L117-125 依赖 notify.py stderr 文本特征串匹配。未来 notify.py 改动任一文案(如「buffer 追加失败」改措辞),P3 会静默落到 else「已入聚合队列」再次误导。 | 读码+实测匹配依赖文本 | notify.py 输出机器可读状态字段(或 stderr 加稳定标记如 `[notify-status=enqueued]`),P3 改按字段判定;或在本函数 docstring 钉死文本契约 |
| caveat | CLI tier 分支恒 `return 0`:append_failed 时进程退出码仍 0,调用方无法从 rc 感知告警未发出。**pre-existing 设计(修复前后一致),且调用方均不检查 rc**,不算本次引入;但「append_failed 不占窗」后 rc=0 语义略别扭。 | 读码 L2149;with_lock/staticdata_sync/backup_async 均不消费 rc | 可选:append_failed 时 exit 非 0(需同步调用方契约),不强制 |
| low | `retry_failed_metrics.py` P3 在 `RETRY_NOTIFY_DRY_RUN=1` 时 stderr 为 `[dry-run] 模拟入聚合 buffer`(不匹配前两分支)→ 打「已入聚合队列」,实际未入队。本地自测场景,影响极低。 | 实测 | 可选加 dry_run 分支 |
| pre-existing(不上报) | `test_notify_dedup.py` L185/L199「rc=2/rc=1」注释描述 repeat_count 但措辞易误读为返回值编码。 | 历史版本 06c44b461 即如此 | 顺手改注释措辞即可,非阻断 |

低分项(<80)已滤:1 项(25 分:`test_notify_dedup.py` 过时 rc 注释——pre-existing,不影响断言)。

---

## 给主控的一句话结论
二轮复审 P0(append 失败假成功占窗吞真告警)已在 8c7601885 **真修好**:独立实测 append_failed 不占窗、不登记指纹、恢复后真入队;三态全 truthy 兼容全部消费点(无 `==1/==2/is True/int()` 消费);suppressed 蕴含「之前已真入队」(追加失败绝不登记 → 无内层指纹窗死链);通用路径 and ok 契约未触碰;7 份测试独立重跑全 PASS。两条 caveat(P3 文本匹配脆耦合 / CLI 恒 exit 0)均为非阻断改进项,**建议 merge**。

## 复现清单
1. `git archive 8c7601885 | tar -x -C /tmp/rev132c` 隔离
2. `cd /tmp/rev132c/scripts && python3 test_132_notify_tier_dedup.py`(13 OK)/`test_notify_dedup.py`(15 OK)/`test_notify_flush_race.py`(6 OK)
3. `bash /tmp/rev132c/scripts/tests/*` 用 `/Users/linhuichen/code/trade-data/.venv/bin/python` 跑 count_file_fail_loud/morning_slot(venv 有 pyarrow)
4. verify_chain 系列(阶段A/B/C/D):buffer 目录 append 失败 → defer_status=append_failed + notify_dedup.json 空 + 指纹状态空 → 恢复后真入队占窗
5. P3 三态:`python3 notify.py subj body --tier warning --from-prefix [告警] --dedup-key X --dedup-window 21600` 三种场景 grep stderr
