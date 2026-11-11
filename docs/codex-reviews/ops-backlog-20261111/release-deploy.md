# HC21 deploy 替代入口闭环 · 2026-11-11

这是用户复核 `d3480ece9cd1669def125889f8f18ce8705a85c7` 后授权扩展 `scripts/deploy.sh` 与对应 tests/docs 的追加交付。继续使用原 `codex/ops-release-gate-20261111` 分支，单 owner；原 [release 报告](release.md)、d3480 提交及其私有证据均保留，不回写。旧报告中“deploy 独立重试未改”的限制由本追加解除，其他未验证范围继续保留。

## 已证问题及修复依据

1. **检查后改树再推**：使用真实隔离 Git 和本地 bare 远端，两侧纯文档各自三检通过，远端并发前进导致首次 push 拒绝。抽取旧 deploy 第 5 步，真实执行 stash/rebase/第二次 push，远端最终接受新树；事后 `check_task_state.py --skip-zombie-crons` exit 1，重复 #499。该检查也是 deploy 原第 1.1.1 步在 push 前执行的检查，旧重试确实能绕过它。
2. **过期 ref 误判成功**：远端仍是旧 base，本地 `origin/main` 被设为当前 HEAD；push 失败且 fetch 返回 128。旧逻辑仍用过期 ref 的祖先关系判成功，返回 0，还把连续失败计数清零。这不是可靠的远端接受证明。

证据在 `/tmp/codex-reports/ops-backlog-20261111/release/deploy-followup/`：`deploy-before.sh` 固定旧源码；`old-bypass.json` 保存真实本地/远端 HEAD、调用轨迹和事后检查；`old-stale-ref.log` 保存误判日志；`red.log` 保存修前用例原始失败。

历史 stash、纯数据冲突选 theirs、连续 rebase --continue 的防御代码是为恢复自动 rebase 服务，解决的是脏文件/冲突导致重试卡住的问题，不能证明改树后的门禁仍成立。实际反例已否定该安全前提。此次删除整个失败后的改树分支，并保留周围逻辑；没有拆掉独立仍在使用的 fetch/push 超时 helper。

## 最小行为改变

首次 push 非零就记清错误、返回原 PUSH_RC（包括 1/124/128），不执行 fetch/stash/rebase/checkout/第二 push，不用缓存 ref 判成功。提示主控先核远端状态、处理原因并更新基线，再重走完整入口；不能只重跑 `--git-phase` 或裸 push。

本次没有新增远端幂等确认。即便远端其实已经接受、客户端仍返回 124，也保持非零和失败记账：未知不能等同成功。主控核实后走完整入口重跑，up-to-date 的真实 push 0 仍走原成功路径。这里以更明确的失败状态换掉未经可靠确认的成功状态，不能保证每个非零都意味着远端未接受。

源码逐字证明 `preservation.json`：失败分支之前与成功 banner 之后均与 d3480 字节一致。故 push 超时预算与 kill/wait/log-tail、两段式锁入口、EXIT 摘要清理/失败 tracker/告警、成功后的静态备份与通知等均未改。删除原 201 行失败块，替换为 9 行停止分支；`git diff` 统计实际 +6/-198（公共行未计入）。`main-merge.sh` 与原 release.md 同 d3480 字节一致。

## 隔离验证

新增 `scripts/tests/test_hc21_deploy_push_gate.py` 共 10 项，复用上一轮临时文档 fixture。只抽三个白名单块：第 5 步 push 判定、原 EXIT tracker、原 push timeout 函数，绝不执行完整 deploy 或其 dry-run。Git 协议限定 file，远端为临时 bare 仓；REPO/GIT_REPO/状态/日志/锁均为临时路径；通知脚本替换为只记参数的桩。

- 实际 non-fast-forward 拒推后原退出码保持；HEAD、远端、staged/unstaged/untracked 内容保持；轨迹只含分支检查和一次 push。
- push 1/124/128 + stale ref/fetch 失败条件全部非零，不 fetch、不改树、不进入成功收尾。
- 远端实际接受但客户端返回 124，仍失败、不猜幂等成功。
- 两次失败触发原阈值告警；标题、severe、dedup key、21600 秒不变；通知桩返回 9 也不改变原 push 128。
- 正常 push 与第二次 up-to-date 均成功，进入收尾标记、重置失败计数；非 main 仍在 push 前拒绝。
- **实际超时**：原 timeout helper 下运行临时假 git + 真子进程，使用原 with_lock。进程实测确认锁在持有；设置预算 1 秒，保留原 5 秒轮询和 2 秒终止宽限，返回 124；父子 PID 均已退出、锁可立即重新获取、tracker 记录 124，日志包含超时与 LOCK_HELD。该用例不声称 1 秒精确墙钟截止。

修前九项的原始末行（不是七个独立缺陷，含更保守的未知结果合同）：

```text
7 failed, 2 passed in 6.10s
```

首轮修后包含 main-merge 回归的原始末行：

```text
2 failed, 22 passed in 20.18s
```

这两项是新通知桩写入的字符串换行导致 SyntaxError；真实 tracker 已正确记录两次失败，但桩未写调用记录。保留 `green.log` 和对应夹具；只修测试桩为 print 写入，无产品变更。后续最终组合结果单独记录，不隐藏本次测试构建错误。

最终组合命令完整保存在 `regression-command.json`；包括新旧 HC21、旧告警黑洞/连续失败记账、失败对象摘要、自愈门、公募预算/净值桶、磁盘形状守卫、告警 L1、registry、版本 TOCTOU、unit 漂移、R2 梯度共 13 个测试文件。所有源形状守卫保留，未找到依赖已删除 retry 字面量的旧守卫，无需删测试。最终原始末行：

```text
153 passed in 77.89s (0:01:17)
```

日志 `regression.log`，退出码 0；运行内层总预算 230 秒、外层 240 秒。`bash -n scripts/deploy.sh`、`bash -n scripts/main-merge.sh` 均 exit 0，无输出；`git diff --check` exit 0。

## 边界与交接

本追加只改 `scripts/deploy.sh`、新增测试、本报告三文件；没有改协调 README、pending-index、其他组代码。原 main-merge 改动继续保留，两个入口均不再检查后自动 rebase/retry。

完整 export/R2/生产 deploy、main 合并、Linux CI 均未执行；整合后的全量 scripts/tests 由父任务执行，Claude 复核后才审合部署。任意外部进程改工作树、定制 Git hook、人工绕过完整入口不在本次保证范围；本次不新增通用并发锁或发布协议。未新建 cron/子 agent，未写生产 DB/R2、未发送真实邮件/飞书/通知、未修改 packet/ACK。所有长任务有总预算并收集到结束，最终交付回执记录无遗留进程。
