# Task#10 数据源韧性修复批·证伪式自测证据(2026-08-27)

> 修复前 FAIL(病灶点名)→ 修复后 PASS,两段输出均由 `scripts/check_ds_resilience.py` 产出。
> 复现命令:`/Users/linhuichen/code/trade/.venv/bin/python scripts/check_ds_resilience.py`(不读写生产 DB,三渠道 stub 全 stub)
> 分支:feat/datasource-resilience(base=origin/main@0fe169f5b)

## 修复前(病灶在位):6 静态 FAIL + 行为级 FAIL
```
# check_ds_resilience @ /Users/linhuichen/code/trade branch-check(证伪式自测)
FAIL  A1 runner BAOSTOCK_WORKERS 默认=1  | default"3"出现2次 default"1"出现0次
FAIL  A2 baostock_parallel 默认 n_workers=1  | 签名默认3=True CLI默认3=True
FAIL  A3 worker 请求间限速 BAOSTOCK_QUERY_INTERVAL
FAIL  A4 worker 失败指数退避 BAOSTOCK_FAIL_BACKOFF
PASS  A4b 10001011 熔断行为保持现状(短路不假重试)
FAIL  B1 mootdx DB 对账函数存在(db_progress_snapshot/load_progress_reconciled)
FAIL  B2 mootdx save_progress 缩水护栏(progress-guard)
FAIL  B3 runner mootdx step 用 reconciled load 切 todo
FAIL  B6 baostock save_progress 同款缩水护栏(同病灶同修)
FAIL  A5 退避秒数函数行为  | worker 无 _fail_backoff_seconds
FAIL  B4/B5 mootdx 行为断言  | AttributeError: module 'ds_mootdx_under_test' has no attribute 'load_progress_reconciled'
FAIL  C组 notify severe 镜像  | TypeError: send() got an unexpected keyword argument 'source'

=== 1/12 PASS ===
--- FAIL 明细 ---
FAIL  A1 runner BAOSTOCK_WORKERS 默认=1  | default"3"出现2次 default"1"出现0次
FAIL  A2 baostock_parallel 默认 n_workers=1  | 签名默认3=True CLI默认3=True
FAIL  A3 worker 请求间限速 BAOSTOCK_QUERY_INTERVAL  | 
FAIL  A4 worker 失败指数退避 BAOSTOCK_FAIL_BACKOFF  | 
FAIL  B1 mootdx DB 对账函数存在(db_progress_snapshot/load_progress_reconciled)  | 
FAIL  B2 mootdx save_progress 缩水护栏(progress-guard)  | 
FAIL  B3 runner mootdx step 用 reconciled load 切 todo  | 
FAIL  B6 baostock save_progress 同款缩水护栏(同病灶同修)  | 
FAIL  A5 退避秒数函数行为  | worker 无 _fail_backoff_seconds
FAIL  B4/B5 mootdx 行为断言  | AttributeError: module 'ds_mootdx_under_test' has no attribute 'load_progress_reconciled'
FAIL  C组 notify severe 镜像  | TypeError: send() got an unexpected keyword argument 'source'
```

## 修复后(最终态):18/18 PASS
```
PASS  A4b 10001011 熔断行为保持现状(短路不假重试)
PASS  B1 mootdx DB 对账函数存在(db_progress_snapshot/load_progress_reconciled)
PASS  B2 mootdx save_progress 缩水护栏(progress-guard)
PASS  B3 runner mootdx step 用 reconciled load 切 todo
PASS  B6 baostock save_progress 同款缩水护栏(同病灶同修)
PASS  A5 退避秒数 30/60/120cap  | got=[(2, 30.0), (3, 60.0), (4, 120.0), (9, 120.0)]
[mootdx-progress] reconcile: 依库对账修正 300 条,宇宙 85 -> 300(库为事实源)
PASS  B4 reconcile 从 DB 重建宇宙(85->300=max对齐)  | universe=300 fixed=300 min_max_date=20260822
[progress-guard][mootdx] REFUSED: 待写 progress 宇宙 85 只 < 库中事实 300 只(库为事实源),拒绝覆盖性写入以防宇宙缩水(同型事故 2026-07-21: 5527->85 致宽度链断供 37 天);如确需缩容请先核查库状态
[notify][severe-mirror] 已镜像登记 /var/folders/xb/5v1hplgn02s6t8q495h5m8fh0000gn/T/tmpzejm9kj0/alerts/latest.md
[notify] 告警已写入 /var/folders/xb/5v1hplgn02s6t8q495h5m8fh0000gn/T/tmpzejm9kj0/alerts/latest.md（保留流水 1 条）
[notify][severe-mirror] 已镜像登记 /var/folders/xb/5v1hplgn02s6t8q495h5m8fh0000gn/T/tmpzejm9kj0/alerts/latest.md
[notify] 告警已写入 /var/folders/xb/5v1hplgn02s6t8q495h5m8fh0000gn/T/tmpzejm9kj0/alerts/latest.md（保留流水 2 条）
PASS  B5a 护栏拒绝缩水写入且磁盘未被破坏  | rc=False disk_len=300 stderr_has_guard=True
PASS  B5b 完整宇宙正常写盘放行  | rc=True
PASS  B5c 空表/新环境护栏退化放行  | rc=True
PASS  C1 send(severe=True) 追加镜像条目(时间戳/级别/来源/摘要)  | len=290 渠道结果={'email': True, 'telegram': True, 'feishu': True}
PASS  C1b dry_run 不落真实镜像  | dry_run 未改变 latest.md
PASS  C2 追加式两条共存+write_alert 区不被抹
PASS  C3 write_alert 重写后流水保留

=== 18/18 PASS ===
```
