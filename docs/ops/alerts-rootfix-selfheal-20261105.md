# 净值自愈保留首轮失败对象（2026-11-05）

本次只在 `codex/alerts-rootfix-20261105` 实施，基线 `6f95913bf`。这是用户“给我看，然后实施”的本轮例外授权；未改默认 Codex 角色规范，不提交、不推送、不改生产。最终审合和上线由 Claude 主控负责。

## 依据与预期

原路径的初检、自愈探针、重出后探针和最终校验各自随机采样。31 桶场景能复现：初检发现失败，但第二轮漏采导致不修；无效重出后再次漏采还可能让已知坏对象被报成通过。

隔离候选 r2 已由 Hubble 定向复核，目标范围无阻断项；对应三文件整体 SHA-256 为 `c7250c93d091ec6824c49878d1c10e597f380e6dcff04d082820359e2b4571de`。该复核覆盖真实 exporter 字段、两份真实基金 payload、上下文绑定和缺参分支，不代表完整生产部署或全史数据验收。

本次实施预期：首轮发现的基金、桶与方向进入既有 summary；即使后续随机漏采，也必须定点复验这些对象。DB 反向、方向未知、输入异常不得授权重出；重出后残留继续阻断。`fund_nav` 的阻断级、`CHECK_RC=${PIPESTATUS[0]}` 和既有 0/3/其他退出语义保持。

## 三处实现

- `check_data_integrity.py`：复用同一个最新三个有效净值点比对函数；结构化记录完整失败对象，不随错误文案截断到三项。summary 绑定实际检查的规范化 `data_dir` 和实际选用的 DB 路径；消费时重新核对当前上下文，不按目录猜 DB、不依 summary 自动换库。`--fundnav-verify-failed` 明确要求 `--data-dir` 和 `--fundnav-failed-summary`，缺参可读退出 2。
- `fund_nav_selfheal.sh`：接收 `FUNDNAV_SELFHEAL_SUMMARY`，探针继续补充随机发现，但已知对象保持定点；重出后复验首轮对象，失败返回 12，并停止后续同步/上传。禁用、避撞窗口、dry-run、最多重出一次及预算不变。
- `deploy.sh`：每次调用用 `mktemp` 建立独立摘要。首轮文件保留不被重跑覆盖；最终结果写入本调用的 `.final` 文件。后续告警正文仍通过本次 `_INTEGRITY_SUMMARY` 变量读取最终结果。

### 摘要留存与清理

只新增一个幂等 helper，复用已有 `_deploy_record_result` EXIT trap 和 `$LOG`，没有新 trap、定时器、巡检或摘要队列。

1. EXIT handler 先保存原始 `_rc=$?`，再调用清理，之后继续原成功/失败/`DEPLOY_RECORD_OFF` 流程。未设置摘要变量、`PY` 或 `LOG` 的早退安全。
2. helper 依次把首轮与最终 summary 完整解析后写入原 deploy 日志，记录 `phase`、来源路径及完整内容。首轮不再被最终结果覆盖，全部失败对象可追溯。
3. 每份内容归档成功才删除本调用对应的文件和 `.tmp`。归档失败保留原文件并打印路径；删除失败也明确打印路径。helper 不改变原始退出码，不发送新通知。
4. 正常 `exec` 重入段2不会执行 EXIT trap，因此在原 `exec` 前显式调用相同 helper。失败 `exec` 再进 EXIT 或重复调用都不会重复归档已删除文件。
5. 只删本调用创建的路径；其他调用的文件保留。留存进入现有 deploy 日志，未另改日志轮转策略，也不宣称外部消费者已全部核实。

首轮摘要和最终摘要均在源临时文件删除之前写入日志；需要恢复内容时，从对应 `[integrity-summary]` 日志行取 `summary` 字段。异常保留文件的后续处置仍归既有排障流程。

## 定向回归与隔离

新增 `scripts/tests/test_codex_fundnav_failed_targets.py`，使用真实 exporter 的 `code/name/source/count/date/nav` 格式，自建 31 桶 SQLite fixture。环境、当前目录和路径修改都通过 pytest `monkeypatch` 自动恢复，不依赖研究 `/tmp` 路径或历史 Git 对象。

业务模块执行前，网络、SMTP、业务 subprocess、shell 与非 fixture DB 出口先打桩并正控。自愈壳只运行 `tmp_path` 中的副本，依赖均为显式桩，PATH 没有系统业务命令兜底；不会执行真实 exporter、锁、通知或上传。cleanup 运行的是真实 helper 和真实 EXIT handler 的临时副本，tracker 为临时桩。

覆盖清单：

| 边界 | 已测行为 |
|---|---|
| 输入 | 坏 JSON、缺上下文、缺参可读失败；合法 payload 正常 |
| 状态 | DB 领先可修；反向/同日异值未知不修；重出失败不重试 |
| 时序 | 重新随机漏采不能丢首轮；无效重出不能洗成通过 |
| 依赖 | 同目录/DB成功，跨目录和跨 DB 拒绝 |
| 极端与回退 | 早退未设置变量、记录关闭、归档失败保留文件 |
| 重入 | 重复清理、正常 exec、失败 exec 保持原始退出码 |
| 作用域 | 外部调用文件不删；未做真实并发压力测试 |

本轮只运行该 module，按命令 25 秒预算分三组、各自使用独立 `--basetemp`：

```sh
python -m pytest -q -p no:cacheprovider scripts/tests/test_codex_fundnav_failed_targets.py -k 'not copied_selfheal and not summary_archive'
python -m pytest -q -p no:cacheprovider scripts/tests/test_codex_fundnav_failed_targets.py -k copied_selfheal
python -m pytest -q -p no:cacheprovider scripts/tests/test_codex_fundnav_failed_targets.py -k summary_archive
```

实际原样末行：

```text
9 passed, 13 deselected in 0.26s
5 passed, 17 deselected in 14.11s
8 passed, 14 deselected in 12.88s
```

合计 22 条通过，不把三组拼成虚构的单次 pytest 末行。首轮完整 module 达到 25 秒命令上限，未计为通过；cleanup 首轮有 `1 failed, 7 passed, 14 deselected in 10.81s`，是测试把失败 exec 写死为 127，而本机 bash 原始值为 126。改为同环境控制脚本对比后，cleanup 八项通过，未改业务退出策略。

完整 `scripts/tests/` 按本轮用户指令由主会话等所有源码稳定后统一跑，本子 agent 未执行；Hubble 的实际 trap/cleanup 独立复核也尚待返回。

## 已知界限

- 上下文绑定是规范化路径身份，不是 DB 内容版本、inode 或跨阶段一致快照；相同路径的 DB 被替换、并发回退不在本次保证内。
- 仍采用既有最新三个有效净值点口径，随机发现补充定点复验；未证明全部基金全史数值正确。
- 无 summary 的独立 legacy selfheal 仍用既有随机探针兼容路径。
- 本次不重出真实产物、不验证生产容量或上传，也未修改前端算法、数值口径和版本串。
- 写码复用点是既有比对函数、summary、EXIT handler、日志和退出码；采用标准库，不新增抽象层或依赖。相关 pending 索引中的净值修复/部署闸门事项未被本次改写；其它 agent 分区文件未触碰。

## r3：Bash 3.2 无 summary 兼容（2026-11-05）

全量回归暴露了实际源码缺陷：macOS `/bin/bash` 3.2 配合 `set -u` 时，空数组直接展开及取长度都可能报 unbound variable。r3 把两处参数传递改为 Bash 3 兼容的条件数组展开（非空元素仍逐项引用），两处长度分支直接判断 summary 是否为空。无 summary 的重出后日志也恢复既有“探针已转 0”语义；不改旧测试，不放宽失败处理。

新 module 增加显式 `/bin/bash` 的无 summary 正常、已新鲜、dry-run、重出失败四例；有 summary 的实际壳调用改用含空格路径，验证参数边界。本机 `/bin/bash` 为 3.2.57；PATH 与 Homebrew 标准安装位置未发现可用的新 bash，不把未运行版本计作通过。

旧 fundnav 模块与新 module 均完整定向运行，每条命令上限90秒，原样末行与命令写入独立 `implementation-selfheal-r3.json`。第一轮旧模块还发现兼容日志缺失，结果 `1 failed, 15 passed in 10.71s` 已保留；恢复旧日志后重新运行两模块。旧 implementation 报告保持原字节，既往源码 review 不沿用为 r3 结论；全量再次由主会话统一跑。

r3 最终两次完整定向原样末行：`16 passed in 10.70s`；`26 passed in 19.52s`。本轮全量未运行，等待主会话及Hubble新差异复核。
