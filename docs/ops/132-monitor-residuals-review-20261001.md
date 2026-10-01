# #132 三条监控残留修复 — reviewer 独立审查报告(2026-10-01)

分支: `feat/132-monitor-fixups-20261001` | commit: `12f6729fa` | 审查: reviewer(独立复现,未改代码)
审查基线: 主仓 origin/main; 复现环境: `git archive 12f6729fa` 导出到 /tmp/rev132, 隔离运行(不碰生产数据/锁/buffer)

## 结论: PASS-with-caveat

三条修复本身方向正确、主路径实测通过、自测真实;但发现 2 个实测确证的实现缺陷
(① 声称的 dedup-key 6h 在 notify.py `--tier` 分支下被静默丢弃,不生效;
② `RETRY_NOTIFY_DRY_RUN=1`(--dry-run)自测模式不生效——defer_warning 不接 dry_run,
测试告警会真入 warning buffer),以及 1 个「先通知后落盘」代价评估错误(实测为每轮重复通知,
非实施声称的「仅多一轮计数」)。均为非阻塞项(生产实际轰炸风险低),按 PASS-with-caveat
放行,3 个 caveat 建议后续修正(见下)。

---

## A. ① 凌晨槽判定 —— PASS

### 独立复现(矩阵,打真实 `_is_morning_slot`)
命令与输出见实施报告复现段(我独立重跑 `scripts/tests/test_132_morning_slot.py` 9 项全 PASS,
与报告逐字一致)。额外构造红线矩阵(实数):

| BACKFILL_SLOT | 实际时点 | 凌晨槽? | gap 处理 |
|---|---|---|---|
| 0200 | 02:10 | True | 静默(gap) |
| 0200 | 03:10 | True | 静默(gap)(#132 核心修复) |
| 0200 | 04:10 | True | 静默(gap) |
| 0200 | 05:10 | False | 计 fail(告警)(该有数据而没有=真故障) |
| 0300 | 04:10 | True | 静默(gap)(唤醒漂移) |
| 0500 | 05:10 | False | 计 fail(告警) |
| 1635 | 16:10 | False | 计 fail(告警) |
| 2100 | 21:10 | False | 计 fail(告警) |
| 空 | 03:10 | False | 计 fail(告警)(手动/update_all 保守) |

### 红线(alert-denoise-keep-fault-discriminator)核查
「凌晨槽该有数据却空着」:
- **05:00 后**启动(唤醒延迟超整夜)六源全败 → 判非凌晨槽 → 计 fail → 告警 ✓(红色保留)
- **02:00-04:59 窗内**启动的真数据源故障(非结构性缺口)会被静默——但该窗本来 82% 是结构性
  缺口(9/14-9/30 十七次 gap/五次 ok),真故障与结构性缺口**不可区分**,且真故障最终由
  16:35/21:00 兜底槽暴露(六源全败=真故障必 fail)+ collect_health 反映 + check_fund
  freshness 检查器兜底。判定=红线**不破**:判别维度仍在(非 gap 失败无条件 fail / 05:00 边界 /
  兜底槽),静默增量仅限「凌晨窗内的结构性缺口」,且该窗静默有历史依据(#84 P1-1)。
  实测确认新逻辑**不会**把「05:00 后该有数据而空」静默掉(见矩阵 0200+05:10 行)。

### 05:00 边界时区
ssh 云上实测: 时区 Asia/Shanghai (CST +0800), `trade-backfill-evening.timer` 下次触发
`Fri 2026-10-02 02:00:00 CST`。`backfill_metrics.sh` 的 `date +%H%M` 与
`_is_morning_slot` 的 `dt.datetime.now()` 同为**系统本地时区**(CST),无 UTC/CST 错位。
05:00 边界 = 北京时间 05:00,语义正确 ✓(注: backfill-evening 实际跑在云上 systemd timer,
「mac 休眠唤醒延迟」注释背景与现部署不符——注释成因是历史 mac launchd 时代,不影响代码语义)。

### 举一反三 hkex_ccass_quarterly.py `_current_slot`
确认同病(原 `startswith("02")` 丢 02:00 强制重算槽)且改法同构(`0 <= hh < 5` 归一 "0200",
无 env 时 `h < 5` 同理)。副作用核查: 新增 03:00-04:59 启动的槽也会触发 CCASS 1h 全量
强制重算(3600s alarm)——设计取舍(强制重算幂等,只多花 ~35-58min CPU,无正确性危害),可接受。
int(slot[:2]) ValueError → hh=-1 → 返回原样(保守),健壮性 OK。

---

## B. ② self_heal 互斥 —— PASS

### 独立复现
`scripts/tests/test_132_self_heal_mutex.py` 5 项全 PASS(独立重跑): 并发两实例 runs=1/notifies=1,
被跳过实例留 audit 标记,均 exit 0,锁不残留(串行 runs+2)。

### 「跳过本轮」自愈性判定
self_heal 每 15min 一轮(云上 `trade-self-heal.timer` 在跑,下次 23:22 CST 实测)。锁被占时
本轮跳过 → 15min 后下一轮再试;retry 是秒级轻量任务,重叠窗极小;失败指标保留 error 态
(collect_health 反映)。**真故障不会被漏处理,最多延迟 15min,自愈成立** ✓

### 锁残留判定
with_lock.py 用 `open(lockpath,"w")` + fcntl.flock(LOCK_EX|LOCK_NB);flock 是 fd 级 advisory
锁,进程退出即释放,lockfile 存在不影响下次 flock。自测「锁不残留」实证 ✓。子进程
(subprocess.run)继承 fd,with_lock 主进程 wait 子进程后退出 → fd 全关 → 锁释放;即使
with_lock 被 SIGKILL,orphan 的 retry 子进程(秒级)持 fd,锁至多滞留秒级。无永久锁死风险 ✓

### 管道语义(∏)
self_heal.sh 头部 `set -uo pipefail` ✓;with_lock.py 拿到锁后 `sys.exit(r.returncode)`
透传子命令退出码 ✓(L154-155 实测读码确认)。retry exit=1 → with_lock exit=1 → pipefail
管道 exit≠0 → `|| echo "⚠"` 接管 ✓。锁被占 → exit 0 → 不误报 ✓。两条链路实施报告已验,
我读码复核一致。

---

## C. ③ 计数文件 fail-loud —— PASS-with-caveat(2 个实测确证缺陷 + 1 个评估错误)

### C-0 关键交叉风险: notify.py 敏感链(必审项)逐条
1. **没有绕过「发送成功才占窗」契约** ✓ — 该契约在 notify.py 通用路径
   L2140(check_dedup) + L2157(`if args.dedup_key and not args.dry_run and ok:
   update_dedup`)。
2. **`--tier` 分支先于 dedup 检查 return = 声称的 dedup 6h 静默失效**(⚠ 见 C-1,主发现)。
3. **dedup key 无命名冲突**: `retry_fm_count_file_write_fail` 全新 key;但该 key 从未生效
   (见 C-1),冲突与否无实际意义。

### C-1 [FAIL 项→caveat] 声称的 dedup 6h 不生效(实测确证)
代码证据: notify.py main() L2070 `if args.tier:` 三分支在 **L2140**
(通用 `check_dedup(args.dedup_key, args.dedup_window)`)之前 `return 0` —
`--dedup-key/--dedup-window` 在 `--tier` 下被**静默丢弃**,不报错不生效。

独立复现命令与输出(/tmp/rev132 隔离 notify.py,REPO=/tmp/rev132):
```
$ python scripts/notify.py "[告警][测试A] ..." --tier warning --from-prefix "[告警]" \
    --dedup-key retry_fm_count_file_write_fail --dedup-window 21600   # rc=0
$ python scripts/notify.py "[告警][测试B] ..." --tier warning --from-prefix "[告警]" \
    --dedup-key retry_fm_count_file_write_fail --dedup-window 21600   # rc=0
warning_buffer.jsonl: 1 行 → 3 行(两次都真入队, 未被同一 dedup-key suppress)
```
实测同 dedup-key 两次不同 subject 调用全部入队 → **6h dedup 不生效**。

实际降噪为何仍存在(风险缓解): `defer_warning` 内部有 4h 同源指纹窗
(warning_fingerprint(subject, body))——生产写失败告警的 subject 固定、body 异常文本稳定
(COUNT_FILE 路径固定)→ 同指纹 4h 内抑制(只累计 repeat_count)。**但**: ①该机制与声称的
「dedup-key 6h」完全无关,实现与注释/报告不符(注释写「dedup 6h」,报告中「持久故障最多
~2-4 封/天」的估算依据错误,实际靠的是另一个未声明的机制); ②若异常文本含变动片段
(如变化路径),指纹每轮变化 → 每 15min 入队 → 30min 聚合批发逐条全发 = 48 封/天轰炸。
建议: 改走通用路径(去掉 --tier,改用 --severe 之外的非通告方式,或给 notify.py tier 分支
补 dedup 支持)。

### C-2 [FAIL 项→caveat] RETRY_NOTIFY_DRY_RUN=1(--dry-run)自测模式不生效(实测确证)
代码证据: send_tiered(tier=TIER_WARNING) → `defer_warning(subject, body, from_prefix)`
(L2011 定义 L2078 调用)——defer_warning **签名无 dry_run 参数,不接 dry_run**;dry_run 只在
flush 阶段(schedule_monitor 尾部 `--flush-warnings`)生效。

独立复现命令与输出(/tmp/rev132 隔离):
```
$ RETRY_NOTIFY_DRY_RUN=1 python scripts/tests/test_132_count_file_fail_loud.py  # 全 PASS
$ cat /tmp/rev132/data/alerts/warning_buffer.jsonl
{"ts": "2026-10-01 23:08:55", ... "subject": "[告警][重采计数] 计数文件写失败, 连续失败告警机制失效", "from_prefix": "[告警]"}
```
自测声称「不真发」,实测 **warning_buffer.jsonl 真写入告警条目 + warning_dedup_state.json
真登记指纹**。影响: 实施在 worktree 跑自测污染 worktree buffer(隔离);但**生产环境手动设
RETRY_NOTIFY_DRY_RUN=1 验证时会真入生产 buffer → 30min 后 schedule_monitor flush 把测试
告警当真发给用户**;且测试消耗了 4h 指纹窗首条(生产真故障时 4h 内被抑制不真发,只累计)。
建议: defer_warning 补 dry_run 短路,或测试改用 monkeypatch 掉 subprocess.run。

### C-3 [评估错误] 「先通知后落盘」代价评估与实测不符(实测 3 轮 3 封)
独立复现(模拟: 计数累计到 2 → 目录改只读 → 每轮达阈值但落盘失败,跑 3 轮):
```
第1轮(写失败): rc=1 notify累计=1
第2轮(写失败): rc=1 notify累计=2
第3轮(写失败): rc=1 notify累计=3
总通知: [('a_fund_main',3), ('a_fund_main',3), ('a_fund_main',3)]
```
推演: 解释: 达到阈值时内存 pop mid 后 `_save_counts` 落盘, 写失败 → 文件保留旧值
{mid: 2} → 下一轮 reload n=3 又达阈值 → 又 _notify_repeat_failure。**每轮都发数据级告警
([告警][重采失败],无 dedup-key = 无任何去重),直到写盘恢复**。
- 定性: 重复通知行为本身是 pre-existing(旧代码 _save_counts 静默不抛时同样每轮 reload 至
  旧值重复通知);本次 diff 未新增该行为,但**实施报告的代价评估结论错误**(声称「后果仅下次
  多一轮计数(非静默类风险),可接受」= 实际「每 15min 一封邮件轰炸」)。
- 与新链路叠加: 写失败期间同时触发 C-1 的写失败告警(4h 指纹抑制),双通道叠加,磁盘满场景
  下用户会收到「数据级重复告警(每 15min)+ 写失败告警(4h 窗)」。
- 按 §10.3① pre-existing 不算 finding —— 本项按「实施评估错误」上报(caveat),建议后续
  专项把它与 6 处静默点一起做(达标通知也应带 dedup-key)。

### C-4 其他验证(全过)
- fail-loud → self_heal `||` 接管: 管道语义读码确认(set -uo pipefail + with_lock 透传
  returncode),C 项 B 已证。
- 自测真实性: 3 份全部独立重跑 PASS,断言的数字(rc=1、通知计数、清零落盘 {})与真实输出
  逐字一致,无假绿。
- 实施自测反例覆盖已全: 我另写的 2 个反例(写失败重复通知轰炸、dedup-key 双调用入队)均
  为实施未覆盖项,结果见 C-1/C-3。

---

## D. 自测真实性 —— PASS

实施侧 3 份自测独立重跑全 PASS(命令见 A/B/C 各节),真代码非 mock(凌晨槽打真实
_is_morning_slot;互斥打真实 with_lock.py;fail-loud 打真实 _save_counts/_load_counts/main
仅 COUNT_FILE 指向临时目录、RETRY_NOTIFY_DRY_RUN 走 notify.py --dry-run)。实施未覆盖的
反例我另写 2 个(见 C-1/C-3)。注意: 3 份自测共 5 处 monkeypatch 均无模块级副作用残留
(临时目录/临时锁),隔离跑不污染生产;唯一隐藏副作用= C-2(dry-run 仍入 buffer)。

## E. 同类错误面抽查(§23.2) —— PASS(缓办合理, 但建议排优先级)

抽查 2 处(均读码确认):
1. `scripts/check_data_gap_alerts.py L1361 _save_state_atomic`: 写失败 except → 仅打印
   stderr,不抛不退出 → 去重/基线状态静默归零 → 告警重复轰炸或漏基线。**确实同族**、
   **确实未改**。缓办理由成立(已上线功能, #123 告警降噪刚评审的敏感链, §23.7 须用户拍板)。
   **建议现在改**: 该文件是告警链路核心, 静默归零直接摧毁 #123 降噪成果,
   优先级应为「静默点 fail-loud 专项」第一顺位。
2. `scripts/feishu_missed_fetch.py L98 _save_cursor`: 写失败 except → log 不抛 → 游标丢失
   → 重复补拉/漏补拉。**确实同族**、**确实未改**(且非原子写,半截文件会令 _load_cursor
   归零→从 0 补拉)。缓办理由成立(低频率任务 + known_message_ids 去重位 + pending 文件
   兜底,影响较低)。
3. 没有该现在就改的与告警静默直接相关的**新增**改动(6 处均为实施已上报的待拍板项,
   按 §10.3⑥ 不重复报);建议主控把「静默点 fail-loud 专项」排入待办,check_data_gap_alerts
   优先。

## F. 冻结契约(§23.7) —— 结论: 本次 3 条修复不需额外拍板;6 处未动项已按 §23.7 上报

本次改动触达已上线行为(retry 退出码/self_heal 调用链/notify.py 新增 tier warning 调用方),
但性质全部是**修 bug**(降误报/消静默/防双通知)且属主控台账 #132 已排派的修复任务授权范围;
§23.7 的「动历史功能必须确认」主要针对行为变更/功能删改,修 bug 例外(23.2 三铁律要求修)。
判定: 不需额外用户确认。6 处同族静默点(fail-loud 专项)实施已列清单上报用户待拍板,
符合 §23.7⑤。

## 发现的问题清单(分级)

| 级 | 问题 | 证据 | 建议 |
|---|---|---|---|
| P2 | 声称的 dedup-key 6h 静默失效(notify.py --tier 分支丢弃 dedup-key) | 实测同 key 两次调用均入队(buffer 1→3 行); 读码 L2070 先于 L2140 return | 修 notify.py tier 分支补 dedup,或废弃 dedup-key 参数走 4h 指纹说明 |
| P2 | RETRY_NOTIFY_DRY_RUN 自测模式不生效(defer_warning 不接 dry_run) | 自测 dry-run 后 warning_buffer.jsonl 真含告警条目; 读码 L2011 签名无 dry_run | defer_warning 补 dry_run 短路,或测试 monkeypatch subprocess |
| P3 | 「先通知后落盘」代价评估错误: 实测每轮重复通知(3 轮 3 封), 非「仅多一轮计数」(pre-existing 行为, #132 评估声明不实) | 反例脚本实测; 读码 main 达标路径 | 达标通知加 dedup-key; 报告声明修正 |
| P3 | 新增告警「计数写失败告警已发(dedup 6h)」打印误导(实际=入 buffer 未发, dedup 不生效) | 见 C-1+C-2 实测 | 文案改「已入警告队列(30min 聚合批发)」 |
| 通过项 | 凌晨槽红线保留(05:00 边界 + 兜底槽 + 非 gap 无条件 fail) | 矩阵实测 | — |
| 通过项 | self_heal 互斥语义正确、无锁残留、pipefail 链路成立 | 自测重跑 + 读码 | — |
| 通过项 | hkex 举一反三同构正确,副作用可接受 | 读码 _current_slot + 调用方 | — |

低分项(<80)已滤: 3 项(25 分: 异常文本稳定性假设、相同时点粒度、hkex 无 env 3-4 点手动跑
触发强制重算的边界——均为低概率/低影响, 未进正式报告)。

## 复现清单(全部可重跑, 命令与输出见上各节)
1. `python scripts/tests/test_132_morning_slot.py` — 9 项 PASS(独立重跑)
2. `python scripts/tests/test_132_self_heal_mutex.py` — 5 项 PASS(独立重跑)
3. `python scripts/tests/test_132_count_file_fail_loud.py` — 全 PASS(独立重跑, 含 dry-run 副作用实证)
4. 反例-1: 写失败重复通知轰炸(3 轮 3 封) — 本报告 C-3
5. 反例-2: dedup-key 双调用入队(buffer 1→3) — 本报告 C-1
6. 云上时区/timer 实测: CST +0800; backfill-evening 02:00 CST; self-heal 15min — 本报告 A
