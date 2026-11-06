# 冻结缺失完整诊断归档（2026-11-06）

来源：用户2026-11-06明确授权诊断落档；不授权历史冻结回补或扩大accepted。

当 `_alert_frozen_missing` 完成精确accepted过滤后仍有事件，使用同一份过滤结果在
`REPO/data/audit/frozen_missing/<run_id>.json` 归档完整集合。这里REPO指脚本已有ROOT，
沿用生产trade-data脚本软链接调用布局。无缺失或全部accepted时不创建目录/文件。

每次调用独立run_id，包含PID、带时区记录时刻、full_guard与NDO/SDC买价口径、
实际freeze路径（解析SIGNAL_KELLY_ETF_FREEZE_PATH并realpath）、metadata_count、
完整filtered_missing、accepted_hits及其数量。metadata_count与原告警n来自同一列表。
诊断run_id是该次guard调用标识，不是上游compute_run_id；没有伪造原运行编号。

仅小源码文件（上限1MiB）和内存缺失集合做SHA-256。source_file_sha256_at_archive是
归档时磁盘源码hash，不声称代表已加载字节码；不可读/过大为unknown。
freeze/map/signal输入hash、latest_signal_date没有传入guard，明确unknown，不另查DB、
不重读冻结内容或映射，不启动外部git。accepted_hits使用同轮已分好的列表，不重读接受表。

复用util_atomic.atomic_write_json在目标目录内独立临时目录写入并fsync，再用同分区
os.link原子发布完整JSON；目标已存在时报错，绝不替换旧诊断。权限0600。碰撞/不可写/
写满等异常只追加一条stderr诊断失败（错误类型），继续原通知，不改变拒冻与退出码。
路径仅写stderr业务日志；UUID和动态路径不进入subject/body/ledger_key/dedup。
export成功路径现有capture_output可能不转发stderr，仍可按固定目录定位诊断。

不新增守护进程、定时任务、状态机、清理策略或依赖；历史归档保留，由Claude另定保留策略。
不追补本次02:13的历史118快照，也不把事后重建集合冒充旧运行证据。

验证：新测试只AST提取真实guard/诊断函数，复用真实atomic helper，全部写临时目录；
通知函数替换为记录器，socket/subprocess外发陷阱带正控。先/tmp旧码失败、候选通过、
撤回旧码再失败；覆盖完整118+accepted8、精确类型边界、小档/大档、空集、重入、
强制UUID碰撞、写失败、路径override、unknown源码hash、通知本身失败。

本地复现：`python -m pytest -q scripts/tests/test_codex_frozen_diagnostics_20261106.py`。
交接主控复核后合入；本任务不commit/push/部署，不改freeze/accepted/compute/resolver。
