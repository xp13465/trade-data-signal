# QVIX 全历史点时验收工具

2026-11-06 用户授权；只读工具，来源保护判定与采集器分离，不接入通知、timer或默认生产链。

## 为什么新增

已检查 `app/history_audit.py`（signal/index历史审计）、`scripts/check_data_integrity.py`（导出产物检查）及 `scripts/tests/test_codex_qvix_fallback.py`（合成SQLite写入保护测试）。它们没有满足“显式只读捕获daily_metric两序列全历史，并跨快照比对value/source/updated_at”的离线CLI；因此只用标准库新增一个脚本，不引入框架/依赖/表。

## 使用

```bash
# 由有权限的runtime操作者执行；本实施未连接真实库。
python3 scripts/check_qvix_history_stability.py --capture-db /absolute/path/sentiment.db > /tmp/qvix-before.json
# 在后一个观察时点另存，禁止覆盖baseline；工具自身只输出stdout。
python3 scripts/check_qvix_history_stability.py --capture-db /absolute/path/sentiment.db > /tmp/qvix-after.json
python3 scripts/check_qvix_history_stability.py --baseline /tmp/qvix-before.json --current /tmp/qvix-after.json
```

只有显式 `--capture-db` 才打开SQLite，`mode=ro`、`query_only=ON`、3秒SQLite progress handler、0.1秒锁等待。不创建缺失库，不用忽略WAL的immutable模式。只查询两指标所有日期和五个必要字段，不采样。最多100000行/16MiB；本轮完整生产基线实际为8753行，另有32000行离线容量验证，超限报错而不截断。输出紧凑JSON。重定向由操作者负责，建议使用全新文件名；脚本不写数据库、不自动存储/替换基线。

## schema_version=1（已同步runtime）

```json
{"schema_version":1,"database_realpath":"/absolute/real/sentiment.db","captured_at_utc":"2026-11-06T00:00:00Z","rows":[{"date":"20261105","metric_id":"a_qvix_300","value":19.27,"source":"akshare","updated_at":"2026-11-05 21:00:00"},{"date":"20261105","metric_id":"a_qvix_1000","value":15.9,"source":null,"updated_at":null}]}
```

必须是同一规范绝对库路径、同两指标集合；两条序列都须存在。单指标/空快照、未知指标、重复(date,metric_id)、非法日期/UTC时间、倒序采样、字段缺失、重复JSON字段、非有限数/bool等为坏输入（exit 2）。若整个指标被删到一行不剩，将作为上下文不完整exit 2，不会假PASS。值允许有限数值（包括0/负数）或null；source/updated_at允许字符串或null，不根据旧标签回滚数据。

## 对比结果与退出码

- `0`：没有需核查变化。新增行（含fallback补任何空日）允许；已有primary/proxy行在after.source=`akshare`时的修订允许，全部逐项记录before/after/fields。
- `1`：存在需核查变化。已有行在after.source=`rv_local`/`sse`时，value/source/updated_at任一变化记`protected_fields_changed`；删除记`deleted`。before或after含手工/未知/空来源的变化仅记`source_change_review`，不是新增业务禁止规则。
- `2`：输入、上下文、查询超时或读取异常。不会以空/截断结果当PASS。

报告中的“受保护字段变化”只是观测事实，不能证明是哪次写入或哪个进程造成；若primary改写后fallback又改写，只凭最终source也不能证明唯一因果。点时快照不能发现两次采样间发生但已恢复的瞬时覆盖；exit 0不能宣告长期根治，须持续由操作者保存不同观察时点的证据。

## 验证边界

定向pytest覆盖主源修订、fallback既有行保护/新增日、删除、上下文/坏输入、nullable值、真实SQLite只读拒写/缺库不创建、32000行全量与真实progress中断。生产、SSH、网络、通知均不执行；不挂timer、不更改默认角色。全量scripts/tests由父会话统一执行，本子任务仅定向pytest和全量lint。提交/push/Claude复核交主会话按本轮授权处理。
