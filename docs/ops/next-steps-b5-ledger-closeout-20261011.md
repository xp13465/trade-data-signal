# B5 台账销账收口报告(2026-10-11)

- 任务:下一步全面方案 v2.1 §B5(盘点 7 条待销账一次清 + 台账对账机检)
- 执行:主控(台账治理本职,§23.12-1)
- 方案:`docs/ops/next-steps-plan-20261011.md` §1 B5;盘点:`docs/ops/next-steps-inventory-20261011.md` §六

## 一、7 条销账动作(逐条)

| # | 销账动作 | 证据(核实物) |
|---|---|---|
| #162 | 状态列「仍未闭」→ ✅ 已闭(10-08 首跑实测 PASS) | merge `31d26421c`;首跑 rc=0/非 143/无 SIGTERM/超时杀痕迹,报告 `docs/ops/s06-timeout-188-verify-20261008.md` |
| #188 | 「真行为考验点(10-08 首跑)」→ ✅ 已 PASS | merge `9c4bffd47`;同 #162 报告 |
| #165 | 「待办」→ ✅ 已完成(10-05 交付,登记滞后) | 实物 `docs/ops/rollback-playbook-20261005.md`(21,134B/237 行);commit `0ffed05c9` 已在 origin/main 链上 |
| #184 | 「待 merge」→ ✅ 已合 main | merge `f06ef83be`(2026-10-07 走 main-merge.sh) |
| #126 | 「可正式画句号」→ ✅ 正式画句号(补记) | 已排除清单 2026-10-01 组在案;收口 commit `ee4a582c4`(云上 staticdata 仓) |
| #219 | 「保留活跃态到 §0 收口」→ ✅ 正式归档 | merge `00229a9b2`;§0 生产观察 PASS 3/3,报告 `docs/ops/219-parts-metadata-prod-observe-20261007.md` |
| 磁盘欠账 6 项 | 已在 #234 行尾「均闭环」记录 → 本次在已排除清单补 bullet | 乙1 p0/107 html 删除报告 `docs/ops/disk-cleanup-batch3-20261010.md`;其余见 #234 行尾 |

## 二、文件改动清单

- `docs/pending-features-index.md`:**7 处** —— 6 处状态列(#162 L258 / #188 L311 / #165 L261 / #184 L309 / #126 L221 / #219 L344)+ 头部「最近更新」滚动 + 已排除清单**新组「2026-10-11 移入(B5 台账销账批)」**(7 条 bullet,插于 2026-10-04 组之前)。
- `TASKS.md`:📍 段状态行更新(B 批开工 5 agent + B5 销账完成 + 巡检 cron id)+ 拍板段(D1-D12 已整体放行)。

## 三、机检证据(commit 前置,3 ok / 0 warn / 0 fail)

```
=== 任务状态一致性对账 ===
  repo:            /Users/linhuichen/code/trade

  ✓ pending_index: pending-index 编号完整性 OK(201 行, 编号唯一, 状态列全非空, 至 #248)
  ✓ tasks_refs: TASKS 编号对账 OK(📍 当前会话状态/📋 待办 段提及编号均可在pending-index/done-list/archive 中找到且无残留关闭指针)
  ✓ zombie_crons: 巡检 cron 检测 OK(2 个巡检 cron: 其余进度文件存在且新鲜, 1 个进度文件触发前待观察(未到应产生时刻, 不计僵尸))
      · cron c9c9d618 进度文件 agent-progress-next-steps-exec-observe1012.md 尚未产生 -> 触发前待观察(首次触发 2026-10-12 09:40 + 宽限 60min; ready_at=2026-10-12 10:40), 不判僵尸

=== 汇总: 3 ok / 0 warn / 0 fail ===
```

复现命令:`python3 scripts/check_task_state.py --repo .`(rc=0)

## 四、连带修复:B 批巡检 cron 机检可解析性

- 现状:`557a2f64`(今早建)prompt 用 glob `/private/tmp/agent-progress-next-steps-exec-*.md` ⇒ 不匹配机检 `PROGRESS_PATH_RE`(只认字面 `/tmp/agent-progress-<name>.md`,且 `*` 非法)⇒ 机检降级「人工核对」warn。
- 处置:重建为 **`f6ddf6d6`**(同 `3,18,33,48` + durable + 门控零输出),prompt 改为**5 个显式单文件路径**列举(b1/b2/b3-verify/b4a/b4b),机检可逐文件核新鲜度;旧 job 已 CronDelete。
- 效果:zombie_crons 维度由 warn → **ok**(见上)。

## 五、状态

✅ B5 完成(机检 3 ok 达成);本报告 + 两文件改动随本节 commit 一并上 main。B 批 5 agent 在跑(巡检兜底 `f6ddf6d6` 在位),收工后 CronDelete。