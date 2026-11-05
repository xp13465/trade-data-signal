# DRAFT — notify closeout 回归测试先行（2026-11-05）

本分支只增加 `scripts/tests/test_codex_notify_closeout_regressions.py` 与本文。
工作分支为 `codex/notify-regressions-20261105`，固定基线为
`6c1493aea9febd6318eafa8a5cf51d0d774aa155`。业务修复仍交 Claude 复核实施。
**本测试先行 DRAFT 不供单独合入 main，必须与业务修复配套。**

当前业务基线的真实结果是 **20 failed / 29 passed，exit 1**。
这些失败表达待修的 desired 契约；没有添加 xfail、skip 或放宽断言。
后述 **49 passed** 仅来自临时测试进程中替换 fixture 模块的最小模拟修正，
不能解读为仓库中的业务实现已经修复，也不是线上验收。

## 契约与测试边界

五条同类 writer 分别为 `_write_result_file`、`_replace_latest`、
`_write_state_obj`、`_save_warning_dedup_state`、`flush_digest` 的摘要 state 写入。
测试实际调用这些生产函数，不用假 writer、预造发送结果或已有测试的假数据作答案。

对于已经存在的目标，复制 mode 时 `stat` 抛 EACCES 或 `chmod` 抛 EPERM，
该次写入必须停止发布，旧目标 **bytes 与 mode 均保持**。调用方原本会吞异常、
返回失败或向上抛错，均可沿用；不会要求通知主链整体失败。
`_replace_latest` 在真实 `.latest.lock` 内执行，warning 状态在 dedup 锁内执行。
故障只在真实 `_chmod_like_target` 的执行期间、指定目标/临时文件上注入，
不会把 `Path.exists()`、读取 buffer 或 pytest 内部 stat 的失败当作产品失败。
测试同时断言故障确实触发；没有触达预期 syscall 也会红。

目标不存在的真实 FileNotFoundError 是正常新建：普通 tmp 按 `0666 & ~umask`，
warning dedup 的 mkstemp 按 0600。分别控制 umask 022/027 并在 finally 恢复。
既有 0600/0640 的正常写入也要保权且实际写入正确的新内容。
摘要核心 `_atomic_write_digest` 另测真实 fchmod 的调用、正确 mode、
fchmod 失败严格保留原文件以及新建默认 mode，避免把严格核心路径改松。

## 基线逐项结果

测试名 `test_metadata_error_keeps_existing_bytes_and_mode[fault-mode-writer]`：

| writer | stat-0600 | stat-0640 | chmod-0600 | chmod-0640 |
| --- | --- | --- | --- | --- |
| result | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） |
| latest | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） |
| state | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） |
| warning_dedup | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） |
| digest_state | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） | FAIL（预期红） |

上述 20 项均失败在旧目标 `(bytes, mode)` 保留断言，而不是环境或 fixture 错误。
普通 writer 发布了新 bytes 并通常变成 0644；warning dedup 发布了新 bytes、
mode 为 mkstemp 的 0600（原本是 0600 的用例仍因 bytes 被替换而红）。

正常保权 `test_successful_writer_preserves_existing_mode[mode-writer]` 与新建
`test_missing_target_keeps_original_creation_default[umask-writer]`：

| writer | 正常既有0600 | 正常既有0640 | 新建umask022 | 新建umask027 |
| --- | --- | --- | --- | --- |
| result | PASS | PASS | PASS / 0644 | PASS / 0640 |
| latest | PASS | PASS | PASS / 0644 | PASS / 0640 |
| state | PASS | PASS | PASS / 0644 | PASS / 0640 |
| warning_dedup | PASS | PASS | PASS / 0600 | PASS / 0600 |
| digest_state | PASS | PASS | PASS / 0644 | PASS / 0640 |

其余逐项结果：

| 测试 / 参数 | 基线结果 |
| --- | --- |
| `test_atomic_digest_real_fchmod_control[0600]` | PASS |
| `test_atomic_digest_real_fchmod_control[0640]` | PASS |
| `test_atomic_digest_fchmod_failure_is_strict[0600]` | PASS |
| `test_atomic_digest_fchmod_failure_is_strict[0640]` | PASS |
| `test_atomic_digest_new_file_default[umask022]` | PASS / 0644 |
| `test_atomic_digest_new_file_default[umask027]` | PASS / 0640 |
| `test_fixed_order_payload_and_buffer_conservation[absorb-first]` | PASS |
| `test_fixed_order_payload_and_buffer_conservation[flush-first]` | PASS |
| `test_lost_new_payload_is_rejected_by_conservation` | PASS（确实捕获守恒失败） |

合计 49 collected，20 failed / 29 passed（1.68s），无 error/skip/xfail。
每项 node id、实际/预期状态另见下方 `baseline-results.json` 与 JUnit。

## 两种并发顺序与负控

使用真实 `fork` 子进程、fcntl 侧车锁、真实 notify 吸收与 flush，
仅在邮件/Telegram/飞书渠道边界打桩。三条渠道分别把 subject、body、pid
写入本轮临时 JSONL，父进程必须收到实际发送子进程的记录。
没有使用不会跨 fork 共享的普通 calls list 作为发送证据。

fixture 独立定义旧 key/hits=2，以及新 key 的三次吸收/hits=3；正文使用唯一标记，
reason 使用支持完整正文输出的 warning-batch 类型。所有“今日”逻辑共用一个
fixture 时钟，避免午夜/23:25 的实际运行时间改变测试结果。

* absorb-first：让第三次吸收已经持有真实锁、准备原子写入时等待 Event，
  再启动 flush；确认 contender 未完成后释放。三条渠道的 payload 均须包含
  旧 key/hits=2、新 key/hits=3 及对应 subject/body，buffer 为零。
* flush-first：让 flush 在持有真实锁的主体入口等待 Event，再启动 absorber；
  释放后 payload 各含旧 key/hits=2，新 key 不在 payload，buffer 精确保留
  新 key/hits=3 与对应完整 subject/body。
* 对每条渠道分别计算“已交付 hits + buffer hits”，与输入 fixture 总账逐 key
  比较，并排除重复行、未知 key 和非发送进程的伪记录。
* 丢内容负控在发送子进程内临时包装渠道：删除新 key 的 payload 明细及正文，
  仍返回发送成功，真实 flush 也照常清空 buffer。
  必须由同一个守恒 oracle 抛出 `payload/buffer conservation failed`，
  测试显式捕获该 AssertionError；不能再以 buffer 空推断已交付。

所有 Process 在 finally 中 release、join；失败时 terminate/kill 后 join，
最终确认已退出并 close 句柄。仅使用 Event/普通临时文件，没有 Manager 常驻进程。
本回归覆盖项目的 macOS/Linux fork 运行环境。

## 隔离与定向复跑

模块导入阶段只定义常量/函数，不改 env、sys.path 或共享 notify。
fixture 用 monkeypatch 临时设置 REPO/GIT_REPO、移除继承的通知控制变量，
再从真实源文件加载一份私有 notify 模块；每个模块级 runtime Path 都须位于
pytest tmp_path。fixture 退出后由 monkeypatch 恢复，不污染其它测试。
路径由 `__file__` 与 tmp_path 推导，没有开发者绝对路径或生产凭据。

网络/DNS/SMTP/HTTP/socket/子进程出口在加载 notify 前拦截，先做 urlopen
陷阱正控，再运行生产函数；后续命中会写临时 guard 日志，包含 fork 子进程。
fixture 收尾断言没有任何后续命中。实际本轮还套用 macOS sandbox 拒绝全部网络、
拒绝生产目录/配置文件内容读取、拒绝临时运行目录外写入，env 只含 dummy 值。

在本分支根目录用新的 `/tmp` basetemp 定向复跑：

```bash
TEST_RUN_ROOT="$(mktemp -d /tmp/notify-closeout.XXXXXX)"
env -i PATH="$PATH" TMPDIR="$TEST_RUN_ROOT" \
  REPO="$TEST_RUN_ROOT/runtime" GIT_REPO="$TEST_RUN_ROOT/dummy" \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -vv -p no:cacheprovider \
  --basetemp="$TEST_RUN_ROOT/pytest" --junitxml="$TEST_RUN_ROOT/baseline.xml" \
  scripts/tests/test_codex_notify_closeout_regressions.py
```

基线 exit 1 是真实预期结果；不要加 `--runxfail`、skip、xfail 或改断言伪绿。
主会话随后在同一固定基线执行完整 `pytest -q scripts/tests/`：
**20 failed / 2358 passed / 3 skipped / 1 warning（268.93s），exit 1**。
20 项失败全部来自上述权限故障用例，没有其它模块新增失败；
测试文件与 notify.py 的运行前后 SHA256 不变。3 skipped 是已有套件结果，
本文件没有 skip/xfail。故本分支仍为红灯 DRAFT，不能单独合并。
全量结果见 `/tmp/codex-reports/closeout-20261105/regression-full-result.json`、
`regression-full.xml` 与 `regression-full.log`；长期摘要同时归档在协作收尾分支。

## 仅内存的最小修正验证

临时 pytest plugin 在 `isolated_notify` fixture 创建私有模块后，
只把该模块的 `_chmod_like_target` 替换成下列函数：

```python
def strict_copy(tmp, target):
    try:
        mode = os.stat(target).st_mode & 0o7777
    except FileNotFoundError:
        return
    os.chmod(tmp, mode)
```

非 FileNotFoundError 的 stat/chmod 错误自然进入五条 writer 原有失败处理。
该函数不写任何业务源文件，fixture teardown 后也不保留模块替换。
同一份 49 项测试在此**模拟修正**下为 **49 passed（1.61s），exit 0**，
证明 20 项红例有判别力且能被最小错误传播修正转绿，而非不可满足的断言。
并发生产函数与其渠道负控未做修正。真实业务代码仍处于基线状态，等待 Claude。

## 本轮证据与交接

* `/tmp/codex-notify-regression-run-e1qc5xxq/baseline.log`、`baseline.xml`：真实基线。
* 同目录 `baseline-results.json`：49 项逐项实际/预期状态。
* 同目录 `memory-green.log`、`memory-green.xml`：仅 fixture 内存模拟后的绿灯。
* 同目录 `run_regressions.py`、`sandbox.sb`：本轮外围 harness 与隔离策略。
* harness 额外核对测试模块单独导入前后 env/sys.path/socket/共享 notify 不变。
* 最初两次 collection 因 sandbox 限制目录 metadata 而失败，日志独立保留为
  `environment-collection-error.log`、`environment-config-metadata-error.log`；
  只放开目录 metadata 后重跑，文件内容与网络限制保持，不计为产品缺陷。
* 交接摘要与进度：`/tmp/codex-reports/closeout-20261105/regression-summary.json`、
  `regression-progress.md`。

未修改 notify.py、其它业务/测试/角色文件。测试作者没有执行提交、清理、
通知或启动 Claude；主会话负责在本独立分支 commit + push 后交接。
Claude 独立复核并提供配套业务修复后，再运行这些 desired 回归及完整测试。
本批前端版本串保持 `20261105-a657` → `20261105-a657`，没有前端变更。
