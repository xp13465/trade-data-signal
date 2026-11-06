# Shared export 与 pending proof 接力（2026-11-06）

本轮修复将“独立上传覆盖台账”与“独占 producer”分开：仅本次实际写出的 shared 产物、canonical root 和实际 bytes 都符合 proof 时，允许 all-data 接管。既有台账、告警阈值和 exclusive 独立链不删除。

## 发布和 proof

- `r2_export_proof.py` 复用原 `build_export_manifest` 的唯一集合；export 的 tab 映射和 manifest 同源。WARN/glob 的存在不等于本 run 实际生成。
- `write_json` 在成功 atomic write 后登记自身序列化 UTF-8 bytes 的 size/SHA256；`main` 在最终 `export_boot` 后发布私有 run proof。嵌套 `signals_today` 的成功写出也进入实际记录。
- deploy 为每次调用建立唯一私有路径/token，显式传过 systemd 环境。proof root 使用 resolved `STATIC_DIR`，错误 root、旧 token、后来改变的 bytes 均不获放行。
- raw shared 保留原 global 豁免，只取对象 key 锁；small 保持原外锁，再由 common worker 取同 key 锁。all-data/intraday/verify 保留原外锁。worker 不重取外层 SH，key 内不再取 data/small；raw 不重复调用持同 key 的 worker。
- key 锁覆盖实际 payload read、proof 校验、PUT/HEAD 和该 bytes 的确认。已有 batch state 仅在成功后原子提交，不引入远端 CAS、版本 receipt 或新队列进程。

## 现有 pending 的逐请求接力

在进入 async 外锁等待前登记请求，timeout hook 再登记同一请求是幂等的。每条记录包括 run ID、canonical root、不可变 proof SHA256，以及记录集拥有的 exact-byte proof 副本路径。目录位于既有 pending flag 旁的 `.contexts`；不是全局 latest 指针。

1. 登记使用 `util_atomic` 的 fsync/replace，并以本地 flock 保护读改写。不同 run 分别保留，同 run 同 hash 幂等，不同 hash 拒绝替换。
2. queue-owned 副本确认后，跳过 caller 可回收其原始私有 proof；在跑 caller 收尾也仅按自己的 run/root/hash 回收原始文件。消费者不会把别人的 caller 路径当作自己的清理目标。
3. 每轮原有数据通道仍执行一次；all-data 移至最后，snapshot 紧邻其调用，故长通道期间到达的请求可加入本轮。正常 worker 仍只有初次和至多一次 catch-up，工作预算参数不扩大。
4. snapshot 每次最多32条，按 offered_at 公平轮转。all-data 分别校验每条真实请求的 proof；只做 current bytes 的 any-match，绝不按请求晚到顺序覆盖一份全局 proof map。
5. all-data 对已获 proof 授权的 shared 文件，即使旧 channel state 指纹相同，也进入 key 锁内确认远端当前 bytes。相同免 PUT/免 purge；不同才上传并 HEAD 确认。这覆盖“all-data state=A，独立上传变 B，再生成 A”的真实指纹盲点。
6. 结果绑定本批 batch ID、请求 ID/hash 和实际确认 payload。全部所需文件已确认，或由同批另一个真实 proof 的 current bytes 取代，才可标 done/superseded。其他数据通道失败、缺 proof、hash 不符或中途 bytes 改变都保留未消费记录。
7. finish 只消费 snapshot 内且当前 hash 仍相同的 ID；不删除后来请求。确认完成后回收 queue-owned proof，保留小型终态记录用于同 run 重试幂等。
8. 旧 flag 用 rename 精确 claim；后来 touch 的新 flag 不会被旧 finish 删除。legacy/no-proof 保留普通非 shared 通道行为，不伪造新的 shared 授权。

最终 snapshot 之后到达的请求允许由下一次正常 worker 消费：其 ID/hash、owned proof 和 pending flag 必须保留，remaining 显式写日志；不能把它报告为本轮已成功。portable 测试真实启动下一正常 worker，verify 仅为禁止修复的桩，证明接力不依赖 verify 擦平。

## 外层轻量对账正文

`finalize_verify` 的非零结果包含 `LIGHT_CHECK_PENDING` 等待验情形，现使用“轻量对账未通过，待核查”，保留实际详情。subject、dedup key/window 和退出行为不变；没有将 pending 断言成确认缺失。

## 验证边界

- portable `test_codex_r2_pending_handoff_20261106.py` 实际运行 async/skip shell、outer with_lock、proof/记录原子操作和完整 uploader CLI 分派；S3、无关上游通道、verify 和通知为隔离桩，零生产调用。
- 覆盖两并发 producer、旧请求晚到、新请求先入、长 drain 期间再入、最终 snapshot 后到达并由下一正常 worker 接手、同 run 重试/冲突、精确 hash ack、missing proof/legacy touch、state A/B/A，以及中性外层正文。
- 相关 R2/manifest 守卫保留原预算和断点断言；feature 关闭时不向旧 `_upload_glob` 调用新增 kwargs。pure inventory helper 纳入 export 代码指纹及临时树依赖；raw canonical 路径有正反测试。

这些是分支实现和隔离验证；生产发布及发布后的真实时序验收由 Claude 主控复核后执行。本轮未执行全量 scripts/tests 或真实 R2 写入。
