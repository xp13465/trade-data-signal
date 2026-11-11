# 例行生产者通知薄补丁 · 2026-11-11

基线 `49fe9bea75d6b2106445a8686a36fc3d51005abc`，独立分支 `codex/ops-quiet-producers-20261111`。按用户本轮明确实施授权；不修改角色规范。开工核对 45 个 worktree，候选 shell 文件无其他未提交修改，Kant/Mendel/accounting 写集不含本次路径。

## 改动与保留

仅四个通知调用增加 `--tier info`，复用现有 dashboard 路由，不新增平台、事件标准或定时任务：

| 文件/分支 | 新行为 | 保留 |
|---|---|---|
| `scripts/update_all.sh` 非 SEVERE 成功分支 | 完成信息仅记内部日志 | SEVERE 告警、后续 daily_summary 业务内容及其失败告警 |
| `scripts/staticdata_backup_async.sh` R2 默认非生产保护 | 仅记内部信息 | 显式放行、内部错误 fail-closed、上传失败收口 |
| 同脚本 git 默认非生产保护 | 仅记内部信息 | git 跳过判据、心跳/退出码、真实备份故障 |
| `scripts/staticdata_sync.sh` git 默认非生产保护 | 仅记内部信息 | SYNC_FAIL=1 与 best-effort exit 0、真实 guard 错误 |

显式 `STATICDATA_ALLOW_PUSH=1` 后的 `check-fresh rc=1` **未降级**：同一返回值包括旧数据/无新增和真实 fetch 失败；本范围不能把混合分支整支静音。若要继续消噪，需 guard owner 先提供结构化原因，再仅降级确定的预期拒绝。未修改 guard 或上述显式放行契约。

## 收口与父调用链核查

- sync 的预期拒绝确实设置 `SYNC_FAIL=1`，但末尾只 echo “同步部分失败”并 `exit 0`，没有二次 notify。保持退出契约不变。完整脚本测试证明一次 info、零 transport 调用。
- async 预期拒绝设置 `_GA_GIT_SKIP=1` / `_SKIP_NONPROD=1`，没有设置 `STATICDATA_FAIL`；真实锁重入结构经受限锁替身执行后，心跳 `skip_nonprod`、exit 0、两条 info、零外发替身调用。若 rsync 或显式上传真的失败，累积 FAIL 跨重入保留，最终 exit 1，现有 `staticdata_backup_fail` 告警仍可达。
- `intraday_snapshot.sh:202` 的 `|| echo` 只在非零退出码进入；`fetch_news.py:766` 仅非零退出码生成 `⚠ [fetch_news] staticdata 同步 rc=...`。预期保护 exit 0 不进入这些失败路径。
- `gen_daily_brief.py:3172` 读取 sync stdout 并通过 `_sync_warn_extra` 保留警示文字。测试将完整脚本的真实 stdout/rc 交给原 wrapper 函数，再用 `gen_schedule_stats.py` 的原 `ANOMALY_RE` / `MARKER_ANOMALY_RE` 核验：例行文字不会转成 log_anomaly；FATAL、真实 fetch_news 非零 marker 负控仍命中。未改 wrapper/监控。
- `deploy.sh:932–965` 判定的是 systemd-run 启动失败；本地 nohup 不等子进程结果。async 正常保护不会制造触发失败。未运行 deploy/systemd/nohup 本体。
- `schedule_monitor.sh:2743` 的 C3 只检查 ok/skip_oversize 的过期时间，skip_nonprod 不进入该分支。因此此次不新增心跳二次告警；这也不能当作非生产 pending 交付超期已被监控的证明。

## 三个 lock skip 不改：缺少静默前提

| 入口 | 已确认行为与具体缺证据 | 后续检测归属/所需接口 |
|---|---|---|
| `on_skip_notify.sh:21` | 只有锁路径；无逐请求 pending、接手/交付回执。with_lock 确认 flock 忙，不证明持锁者是能完成该请求的合法任务 | producer/锁 owner 提供 run/请求与接手者绑定；Mendel 的 schedule 任务漏跑/进行中超时目前是任务级，需证明覆盖被跳过请求的交付期限 |
| `turnover_backfill_skip_notify.sh:22–29` | 无 pending；跳过却写标准开始/结束与 exit 0，普通任务日志可被当成正常结束；不能据此证明产物新鲜 | turnover/Ops 交付证据 owner 用同 run 的产物/发布确认驱动超期；schedule 消费该事实，不能只看 skip 的 exit 0 |
| `r2_upload_skip_notify.sh:42–64` | 有逐请求入队，但 enqueue 失败仍继续“已保存”文案/同一通知分支；仅锁路径，没有合法持锁者绑定。正常 worker 有界补跑，晚到记录留给下次，未证明逐请求截止时点消费监控 | R2 pending owner 提供成功入队证明、接手者/截止期；Ops/schedule 对未消费/未知交付记录按期限检测，再只对已保全且有合法接手的 skip 使用 info |

未修改三脚本，也未把注释“下轮会补跑”当作交付保障。未修改 with_lock/upload_r2/notify/schedule/其他组文件。

## 离线验证与边界

专属用例 `scripts/tests/test_ops_quiet_producers_20261111.py`：真实 shell 分支及两个完整 staticdata 脚本，真实 notify CLI/分级/dedup/info 落盘，三渠道 transport 替身。REPO/GIT_REPO/MAIN_REPO/config/静态数据/日志全临时隔离；PATH 白名单，git/rsync/guard/锁/上传受限替身。legacy plist sed 也是替身，不读取主机 plist 内容；不改 HOME。notify 导入前阻断 socket/DNS、非允许进程与临时根外写入。每个 shell 15 秒进程组上限，超时收集并清理进程。

修前原始末行：`5 failed, 16 passed in 6.23s`（四处真实外发替身反例及成功后业务失败用例）。修后原始末行：`30 passed in 11.91s`，含完整流程、旧版临时副本反例、父 summary/监控匹配；原始日志 `/tmp/codex-reports/ops-quiet-20261111/producers/final-tests.log`。三个 shell 分别 `bash -n`、`git diff --check`。

正负控覆盖：正常成功、默认保护、生产/显式放行、guard 内部错、fresh 混合拒绝/内部错、业务速递可达及失败、仓库缺失、持续备份失败、完整脚本 rsync/上传失败收口、真实父 wrapper 与监控模式。没有运行真实采集、git/R2 业务写入或通知；不声称全链生产验收/14天零噪音。全量套件与合并后通知/调度合同复核由父统一整合。

可逆性：撤销此提交即可恢复四个调用原路由；业务判断/锁域/退出码不变。复核请重点看真实失败仍可达和三条 skip 保留的缺证据，不将本补丁扩大解释为全体报告静音。
