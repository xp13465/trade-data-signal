# R2 逐请求只读观察（2026-11-11）

基线 `30df57e6bc20d15c7ec82c14c60626476ab7d622`。仅扩展 `scripts/r2_pending_context.py` 的观察接口、专属离线测试与本文；不更改 enqueue/snapshot/finish/retire-source，不新增队列、worker、守护进程，不改变 skip 或通知。父任务独占 ops_monitor 接线及其测试。

## 接线接口

```python
from r2_pending_context import inspect_contexts

# cfg.r2_pending_flag 缺省 None：父 collector 自行返回“未配置 unknown”，不读取生产默认目录。
report = inspect_contexts(
    cfg.r2_pending_flag,
    cfg.data_root / "static-site",
    limit=32,                         # 1..128
    budget_seconds=min(remaining, 5), # 0..5；0 不做文件读取
)
evidence = report["summary"]
# 等价：project_observation(report)，纯内存投影，不做文件读取。
```

完整签名：`inspect_contexts(flag, root, *, limit=32, now=None, budget_seconds=5)`。
`now` 为可选 Unix 秒观察时点，默认取当前时间；用于可重复离线检查，不是 SLA。
不接受负数/非有限/布尔预算；无效 API 参数抛 `ValueError`。文件不可读等观察问题返回结构化 unknown，不抛出路径相关异常文本。

summary 固定 18 个 scalar，无路径、自由文本或凭据：

| 字段 | 含义 |
|---|---|
| status | `unknown` / `warning` / `empty` |
| reason | `inspection_incomplete` / `invalid_request_evidence` / `pending_without_deadline_contract` / `no_pending_requests_observed` |
| inspection_status | `complete` / `incomplete` / `unavailable`，只表示本地检查完整性 |
| pending_count, missing_count, done_count, superseded_count, unknown_count | 已观察到且属于当前 root 的状态计数；身份无法确定的记录计 unknown，不忽略 |
| proof_invalid_count | 已观察到的 invalid/missing proof 数 |
| invalid_record_count | 带有 issues 的记录数 |
| oldest_wait_seconds | 当前未消费请求中可计算的最大等待秒数；无有效值为 null |
| unoffered_count | 未消费且 offered_at 为 0、时间戳有效的记录数 |
| records_scanned, entries_scanned | 实际读取的记录数、检查的目录项数 |
| other_root_records | 读到但过滤掉的其他 root 记录数；仍占预算 |
| truncated | 是否达到记录/目录项/时间预算，未检查范围不可推为完整 |
| deadline_status, public_bytes_status | 始终 `unknown` |

summary 键不含 path/log/email/env/token；字符串无斜杠、长度不超过 400。完整 report 另含 `records`、`counts`、`issues` 和 `limits`；不返回 root/proof_path/original_path。record 提供真实 `id/run_id`、state、consumption_status、proof_integrity、created_at/offered_at/completed_at、wait_seconds、since_last_offer_seconds、proof_sha256、issues。非法数字时间戳输出 null，不输出 NaN/Infinity。

## 判定语义

- 完整扫描无当前 root 的未消费请求：`empty` 只说明未观察到 pending 请求。legacy flag 可仍存在；业务成功、当前 public bytes、legacy 工作均未验证。
- pending 且 owned proof 完整：`unknown / pending_without_deadline_contract`。等待时长从 created_at 算起，不被 offered_at 重置；offered 只表示曾交出，不是正在执行或已消费。
- missing、坏 JSON/身份、坏 proof、非法/未来时间：不报健康；可确定证据损坏时 `warning`。
- 读取失败、锁忙、并发变化、范围截断：`unknown / inspection_incomplete`；保留已读原始计数，不能当队列总数。
- done/superseded tombstone 且 owned proof 已删除：合法 `retired`；需要完整身份/hash/path、有效 created/offered/completed 时间链。等待时长止于 completed_at。若残留 proof 存在则仍校验其 bytes/hash/schema，不跳过坏残留。
- 本地 proof 校验只覆盖 owned 副本的 SHA256、run/root 身份及 output size/hash 结构，不读取 payload、不发 HTTP、不声明当前公开数据正确，也不是再次授权上传。
- 现有记录 schema 没有可追溯、明确绑定请求的业务期限合同，本接口不发明合同。deadline/SLA 和 public bytes 均 unknown；任意新增 deadline/sla_seconds 字段不会被默认为已批准合同。去重窗、进程 timeout、此接口 5 秒预算都不是业务 SLA。未来引入真实合同须单独审定 schema/来源及绑定规则。

## 只读与边界

只打开已存在的 `.contexts/.lock`，尝试 `LOCK_SH | LOCK_NB`，不创建锁/目录，不触碰 pending flag，不写扫描游标。保持原生产者的排他锁协议；只读共享锁可能短暂阻挡随后开始的 writer，最大正常扫描预算 5 秒。

从 `/` 用 no-follow 目录 fd 逐层打开；仅兼容 OS 的 `/tmp` 别名，其他符号链接（包括父目录）拒绝。context 目录须属于当前有效 UID 且不可被 group/other 写。记录/proof 要求私有普通文件、同 UID、单 hardlink；锁允许旧实现默认的只读 group/other 权限，但不能 group/other 写。FIFO/特殊文件不阻塞读；proof_path 必须与现有 id/hash 推导的 owned 文件严格一致，不读取原始 caller 路径。

在文件读取前后检查 inode/size/mtime/ctime/mode/link/UID，结束时复查已读文件、缺失 proof、锁、目录及目录路径。检测到并发非协作改动即 unknown；这是观察时点的诊断，不是阻止同 UID 恶意 writer 的安全边界，也不承诺返回后文件不再变化。

默认最多 32 条记录，可降或升到 128；含其他 root/坏记录。最多 1024 个目录项，最多探测额外一项以识别截断。每份 record 64 KiB、proof 1 MiB（读取多一字节用于确认上限）。时间预算为协作式，在目录循环与收尾检查，不能中断已进入内核的文件系统调用；调用方若需要硬墙钟上限须用自身进程隔离。无游标、无分页完整性承诺；有超范围数据就 unknown。

CLI 保持既有环境参数：

```bash
REPO=/absolute/isolated/repo R2_UPLOAD_ASYNC_PENDING=/absolute/isolated/pending \
  python3 -B scripts/r2_pending_context.py inspect --limit 32
```

只输出 JSON；本地检查完整时 exit 0（即便业务为 unknown），不完整/不可用时 exit 2。不能用退出码宣称交付成功。生产环境必须由部署方核对实际 producer flag；本轮未调用生产 CLI、未发真实通知。

## 离线验证

```text
python3 -m unittest discover -s scripts/tests -p 'test_r2_pending_inspect_20261111.py' -v
Ran 27 tests in 0.140s
OK

python3 -m unittest discover -s scripts/tests -p 'test_codex_r2_pending_handoff_20261106.py' -v
Ran 9 tests in 28.183s
OK
```

新增测试使用真实文件、真实 enqueue/snapshot/finish、真实 flock、真实 symlink/hardlink/FIFO；竞态在精确读点注入真实写入/rename。CLI 另在 Python audit guard 下运行，禁止文件写入/rename/unlink、socket、子进程/系统命令，并对调用前后完整隔离目录 bytes/mode/mtime/ctime 作一致性比较。覆盖缺目录/缺锁、坏 proof、未来/非有限/逆序时间、合法终态回收、预算耗尽及摘要约束。现有 9 项回归实际执行 async/skip shell 与上传入口，R2 和通知用原测试的隔离桩。
