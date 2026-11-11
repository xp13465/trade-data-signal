# D1 复核修复 — BETA-D1-001 / BETA-D1-002

本次按用户明确授权，在独立 `codex/ops-d1-repair-20261111` 分支实施。从 integration 固定 `072887593797be94ac2af58b4b8a9bc17ffa9b9c` 新建工作树；不延续或改动已交付FX分支。原 `/tmp/codex-reports/ops-backlog-20261111/review-beta/report.json` 的FAIL及独立证据保留不改。本文件是修复说明，不把原审查结论回写为PASS；最终完整head与自验结果在 `/tmp/codex-reports/ops-backlog-20261111/d1-repair/report.json`。

## 先复现

两份原独立probe逐字节复制到新的before目录，仅通过该目录的base/snapshot链接选择输入源码；未改probe断言/样本，也没有写回review-beta。snapshot的helper/lib逐字节核对固定base。

| 原负控 | 修改前 | 修改后（最终代码） |
| --- | --- | --- |
| 真实 `d1_execute_sql_file`，stdout 65536个O、stderr跨PIPE_BUF边界的syntax error，业务rc7 | base只执行1次；integration执行3次，fatal词被转发片段打断 | base/修复均只执行1次，rc7，syntax error完整，输出均66067字节 |
| stdout/stderr别名到同一满管道，仅腾出一个PIPE_BUF空间，不恢复读取 | 5.006秒仍未退出；恢复读取后才124 | 不恢复读取，3.101秒已退出124，子进程组回收 |

原始日志：`before/retry.log`、`before/backpressure.log`、`after/retry.log`、`after/backpressure.log`。本机该负控运行值为PIPE_BUF=512、管道填充65536字节。该数值不写死为生产平台常数。

## 实现

P1由输出拓扑变化引起：同一接收端原本接收子进程合并写入，旧观察器改成两条PIPE后按转发块轮流写，破坏了错误词。现在共享管道/套接字按fstat识别同一底层接收端，使用 `stderr=subprocess.STDOUT`，子进程只写一条合并PIPE。单条PIPE的读块边界不会再插入另一观察队列的字节。

普通文件“同inode”不证明两个描述符共享偏移：两个独立open同名文件可以有不同offset，因此不靠inode猜别名。实际 `d1_execute_sql_file` 的 `>out 2>&1` 在shell显式声明 `D1_METRICS_MERGED_OUTPUT=1`，helper以 `--output-mode merged`接收声明并核对同一接收端。其它既有调用仍传separate；两个同inode但独立打开的文件不自动合流。没有改变SQL致命错误正则、业务重试次数/间隔/预算或COUNT判据。

P2由阻塞write对可写快照的错误信任引起：select不为别名描述符各保留一份空间。现在合流只有一个pending队列，并对管道/套接字采用非阻塞write。EAGAIN只保留待写块等待下一轮，不丢字节、不改变业务rc；事件循环可继续检查原deadline，终止后最多2秒排空。退出finally恢复输出描述符状态；普通文件不改变状态标志。满/关闭的警告接收端也采用非阻塞写，防止清理后又卡在warning；有可用诊断FD9时继续沿原通道发警告。

依据：[POSIX write](https://pubs.opengroup.org/onlinepubs/9799919799/functions/write.html)规定，PIPE_BUF范围的非阻塞写在空间不足时返回EAGAIN，而阻塞写可以等待；大于PIPE_BUF的多线程写入本来就不保证不交错。[Python os阻塞模式说明](https://docs.python.org/3.11/library/os.html#os.set_blocking)对应O_NONBLOCK。两页只读限时获取，原件保存在本次证据目录；没有请求Cloudflare生产接口。

合并后不能恢复字节的stdout/stderr归属，回执明确新增 `response_observation.stream_mode=merged`、`merged_bytes/merged_sample_bytes/merged_overflow`；原stdout/stderr各自计数及溢出字段为null，不能把合并输出全算作stdout或虚报stderr=0。分流模式原计数保持不变。原元数据白名单、缺失null、禁止累计相加、call/attempt去重和原子写协议不变。

内存仍有界：每个逻辑流最多64KiB待转发，最多1MiB样本；合流只有一个逻辑流。溢出丢弃样本、继续转发，计数不可用而不是补零。没有新增原始响应落盘文件、远端调用、SQL或业务重放；原业务out文件仍归原调用者。

## 验证

新增21个回归用例留在既有D1测试文件，不新增CI路径、也不改CI配置：

- 全部7类既有SQL fatal关键词跨转发边界，stdout-first/stderr-first两种顺序；网络错误负控保持3次，SQL错误均1次，rc7和字节顺序/长度不变。
- 真实子进程及孙进程，共用输出管道；满容量与只释放一次PIPE_BUF两种情况，无消费者配合也限时退出，核父子进程已结束、描述符状态恢复、回执forwarding_failed。
- 同inode独立open的反向负控；不错误合流、不调用F_SETFL修改普通文件。
- 模拟select之后空间被占的EAGAIN竞争，待写数据仍完整、业务rc0。
- 完全填满警告管道，warning有界返回且状态恢复。

既有D1用例继续覆盖每流18MiB、rc0/7、退出前可见输出、样本溢出不重试、真实进程组timeout、独立流背压、ENOSPC目标排空、并发/锁/容量/身份等。

额外逐字节复制运行独立复核probe：

- `probe_sqlite_sync.py`：两个真实sync入口、真实生成SQL在隔离SQLite执行；migration/hash_prefetch/import/count_verify全链。每表正常COUNT rc0，故意COUNT=999 rc1；远端替身库均保留3条fixture行，元数据不含SQL/行结果/凭据标记。
- `probe_enospc.py`：在真实shell重试入口令persist抛ENOSPC。业务rc0、只执行1次、二进制stdin和双流输出完整、warning可见但不泄漏异常文本、证据0文件。不能把“证据未保存”改成业务失败重放。
- `probe_warning_backpressure.py`：修改前后该特定分流探针本来都约3.1秒退出；不把它虚报成新发现。新增完全填满warning管道的回归另行覆盖保底出口。

测试命令（外层进程组总timeout180秒，日志落/tmp，超时killpg并wait回收）：

```sh
REPO=/tmp/d1-repair-testdata GIT_REPO=/tmp/d1-repair-testdata /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_d1_metrics_evidence_20261111.py scripts/tests/test_pfscore_d1_single_import_20261026.py scripts/tests/test_d1_incremental_sync_20261108.py scripts/tests/test_d1_index_idempotency_20261109.py scripts/tests/test_d1_selective_upsert_20261109.py scripts/tests/test_275_d1_sync_visibility_20261022.py --tb=short
```

执行器均为本地fake npx，REPO与数据根隔离，凭据/状态工具按既有fixture stub。真实子进程不等于真实D1执行；本次没有生产D1请求、通知、部署或消息ACK。

两轮失败日志保留：首轮 `6 failed, 137 passed in 50.93s`，修复旧Bash严格模式下空数组参数错误；第二轮 `1 failed, 142 passed in 51.79s`，剩余断言误把普通文件写入后内核维护的状态位当作未恢复。独立直接write、不经过observer同样从1变65537（`direct-write-flags.json`）。最终测试改为核公开状态标志并禁止普通文件F_SETFL，未掩盖产品失败。

最终测试原始末行见本文件末尾与私有report.json。变更Python源码compile、`bash -n scripts/lib/d1_execute.sh`、`git diff --check`均验证；提交时继续正常pre-commit lint。

## 限制与交接

- 只验证本机与本地替身；没有Linux运行、真实Wrangler/D1自然轮、生产账单或全量仓库测试。父任务统一整合，原FAIL交Claude复核修复证据。
- 同一合并PIPE保留OS实际收到的顺序；不是对不同进程大于PIPE_BUF并发写入的全局时序证明，也不承诺消除子进程原本就存在的分段交错。无法从合流倒推出每条原stream计数。
- 非阻塞状态临时作用于继承的open-file-description，其别名在执行期间可见；正常返回、处理到的SIGTERM/SIGINT和内部timeout均finally恢复。外部SIGKILL/断电不执行finally，仍不能保证最后一条回执或状态恢复。普通文件/设备自身卡死不由O_NONBLOCK解决，不把本次管道deadline证明外推为存储故障的硬实时保证。
- 超时/不可写消费者可能收不到全部字节，回执明确forwarding_failed；warning接收端也满时警告允许丢弃以保业务rc和退出边界，不能声称警告必然送达。
- 原metadata样本/回执容量、loaded Python与shell身份范围限制沿用；不把已读HEAD当作完整已加载shell证明，不新增远端确认或补跑。
- 本任务仅改下列4文件，原review-beta报告及FX分支未改，CI/其他组文件未改；不合main、不部署、不发布packet或ACK。

文件清单：

- `scripts/d1_metrics_evidence.py`
- `scripts/lib/d1_execute.sh`
- `scripts/tests/test_d1_metrics_evidence_20261111.py`
- `docs/codex-reviews/ops-backlog-20261111/d1-repair.md`

最终定向测试原始末行：

```text
143 passed in 56.60s
```
