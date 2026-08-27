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

## Phase 2 追加(2026-08-27 第二次 commit):18/18 → 32/32 PASS

> Phase2 范围:T3 akshare 东财三级兜底转正(mootox_daily 内嵌写同表)+ stock_daily T2 三件套配套
> + runner stock_daily step reconciled 接线 + T4 换手率备源参数化(cleanup_d3d2 source=mootdx)
> + 机检 D 组静态 8 项+行为 6 项。证伪式证据:D7b 首跑 FAIL(gt5_pct 期望写成 1/3,尺子算错,
> 实现返回 2/3 正确——[2,6,12] 中 >5 有两只;修正断言后 PASS,L42「尺子先验证」现场印证)。
> 注:头部分支行 base=0fe169f5b 为 Phase1 初次 push 时快照;实际远端 feat 现指向含 Phase1 的
> 5258a3687(base 已前进至 1ab3d3e58),Phase2 commit 叠加其上。

```
PASS  D1a mootdx akshare fallback 函数与预算常量
PASS  D1b akshare fallback 契约三件(fetch_one/CooldownError捕获/北交所skip)
PASS  D1c 12列->10列映射取[0..7,9,11](amplitude/pct_amt弃,turnover服务端值)
PASS  D1d run_batch 两处接线(client失败分支+aborted分支)  | 调用点=2 接线段=2处
PASS  D2 stock_daily T2 三件套(snapshot/reconciled/护栏)
PASS  D3 runner stock_daily step 用 reconciled load
PASS  D4a cleanup turnover 取数 source 参数化(baostock默认+mootdx表映射)
PASS  D4b CLI --source 校验只放行 baostock/mootdx
PASS  D5a fallback 覆盖口径+去重+progress 固化  | total=1 ok=1 skip_bj=2 calls=['000001']
PASS  D5b 12列->10列映射精确值(amplitude/pct_amt弃)
PASS  D6 stock_daily 护栏拒绝缩水(50<120)
PASS  D7a cleanup 非法 source raise ValueError(腾讯源不存在,防误配)
PASS  D7b compute(source=mootdx) 剔NULL聚合五指标正确  | mean_0822=6.6667 gt5=0.6667
PASS  D7c upsert_turnover source=mootdx 标记入 daily_metric  | sources={'mootdx'} rows=10

=== 32/32 PASS ===
```

### D5/D7 行为口径(1:1 直白)
- D5:临时库 mock `stock_daily.fetch_one` 返回 12 列样本(code,date,o,h,l,c,v,amt,amp=20,pct=4.56,pct_amt=3.21,to=9.10);入 baboon 库后第 9/10 列应=4.56/9.10(amplitude/pct_amt 被弃);北交所 830799/430047 跳过计数 2;600000 progress 已到 today → 零请求去重(CALLS 仅 ['000001'])。
- D7b:0822 塞 [2,6,12]+一行 NULL turnover → mean=(2+6+12)/3=6.6667、gt5=2/3(NULL 剔除);0821 [1,3] median=2.0。
- D7c:daily_metric(schema 同 app/db.py PK(date,metric_id))写入后 DISTINCT source={'mootdx'},10 行=2 日×5 指标。

## 复现

- 脚本:`scripts/check_ds_resilience.py`(头部 docstring 含目的/口径/输入输出)
- 命令:`/Users/linhuichen/code/trade/.venv/bin/python scripts/check_ds_resilience.py`
- 输入依赖:仅仓内源码+tempfile 临时目录;生产 DB/三渠道均不触碰(stub)
- 口径一句话:A=T1 并发限速,B=T2 库为事实源双层根治,C=L46④ severe 统一镜像,D=T3/T4 备源转正与配套护栏

## P2 内审修复批(2026-08-27 第三次 commit):32/32 → 38/38 PASS

> 内部 reviewer PASS 无 P0/P1,三个 P2(均为新增防御代码自身边界):
> - P2-1 notify `_mirror_severe`:read-parse 在 fcntl 锁外→两条 severe 并发 lost update。
>   修法=新增 `_update_latest` 单一入口(flock 临界区覆盖 read+parse+compose+原子替换),
>   `_mirror_severe`/`write_alert` 均改走它,锁外零直读。
> - P2-2 mootox `db_progress_snapshot` 空库/表不存在抛 OperationalError(init_db 前)。
>   修法=sqlite_master 表存在性检查返空 dict(_db_code_count 容错同哲学);
>   同构 stock_daily 一并修;baostock 新增版原生带容错。
> - P2-3 读取侧覆盖不全:裸 load_progress 还在执行面(one/upone 单笔读改写在护栏
>   场景会被误拒、full/run_batch todo 切面缩水放大)。mootdx CLI 4 处+update_one 兜底、
>   stock_daily run_batch+CLI5+update_one 兜底、baostock 三件套新增(r/o 复合段
>   只增不减)+run_update/run_batch_segment/rebackfill/stats/one/upone 全换 reconciled。

```
PASS  E1a P2-1 统一入口 _update_latest(flock+read+compose 同锁段)
PASS  E1b _mirror_severe 锁外零直读(read_text/parse 已下沉锁内)
PASS  E1c 8线程并发 severe 镜像零丢失  | entries=8 errs=[]
PASS  E2 空 DB(无表)snapshot 三模块容错返空不抛  | sizes=[0, 0, 0]
PASS  E3 读取侧闭合(裸load仅剩三件套内部,reconciled接线>=5)
PASS  E4 baostock reconciled 恢复 r/o 复合宇宙+固化  | universe=3 fixed=4 disk_match=True

=== 38/38 PASS ===
```

### 尺子自纠两处(§23.9⑤ 1:1 自查手段印证)
- E4 首跑 FAIL:测试数据种子写 "20250601" 当 old 段——字符串序 '20250601'>'20160101'
  根本不在 old 段(<2016),应写 "20150601";实现无问题,尺子修正后 fixed=3→4 段全部拉高。
- E3 首跑 FAIL 发现 rebackfill 兜底分支还有一个裸 reload 漏换(reconcile() 后
  `progress = load_progress()`),补齐后才真闭合——机检反向揪出实现遗漏,正是其价值。

### baostock_daily.load_progress_reconciled 口径(新增,与前两模块差异点)
progress 结构为 {code:{r,o}} 复合段:r/o 分别与 DB 两段 MAX(date) 只增不减;
n_fixed 按「段」计;save_progress 固化失败不阻塞采集;旧 reconcile() 保留不删
(runner L392/L576 仍调用,<4000 阈值触发路径不受影响)。

## 复现(P2 批)

命令不变:`/Users/linhuichen/code/trade/.venv/bin/python scripts/check_ds_resilience.py`
