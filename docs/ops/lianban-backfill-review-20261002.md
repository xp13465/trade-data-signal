# 连板历史回补脚本独立审查报告(reviewer,2026-10-02)

> 审查对象:`app/backfill_lianban.py`(449 行)+ `docs/scripts/sent_impact_lianban.py` + `docs/scripts/verify_lianban_fillgaps_zerotouch.py` + 三份配套文档。
> 工作目录:`/private/tmp/revlianban-wt`(feat/lianban-review-20261002 @ 76349cde1);测试在 `/tmp/lianban-rv-src` 沙箱全 mock,未碰任何生产库。
> **本次不复核数据**(生产写库结果已由 tester 独立核验 PASS:ADDED=1154/REMOVED=0/CHANGED=0、重叠段逐行 diff=0、备份 integrity ok),只审脚本正确性/安全性/可复用性。

## 0. 结论

**PASS-with-caveat:可合入 main 留档**。核心语义(只补缺口/manual 保护/幂等/原子性/dry-run 同路径/竞态加固)全部经沙箱 mock 逐项验证为真,生产实跑 + tester 独立核验背书。合入前建议顺手补 1 个 P1 加固(翻页兜底),P2 项登记不阻断。

## 1. 必查项判定与证据(10 项)

### 1.1 「只补缺口」语义 — PASS(with 2 个边界 caveat)
- 判定链:db.py:182 `_existing_map` 只取 `value IS NOT NULL` 行 → 循环内 `old=existing.get(d)` → manual 先行跳过 → `fill_gaps_only` 下非空值跳过 → 仅缺口(无行/NULL 值行)进 `rows` 计划写入,`_upsert` 再以 `only_if_null=True` SQL 二次兜底。
- 沙箱实测:
  - 已有非空值(akshare 5.0)+ FAPI 新值 7 → `skipped_existing=1`,库保持 5.0 ✓
  - NULL 值行(akshare NULL)→ 补齐为 fapi 值 ✓(`_existing_map` 排除 NULL=视作缺口)
  - **边界 value=0**:0 是非空 → 跳过不覆盖(实测 planned_write=0,库保持 0.0)✓ —— 符合「已有值一根汗毛不动」
  - **边界 value=空串**:`_existing_map` 视空串为已有值(`'' is not None`)→ 走 skip 分支 → **verbose 打印 `{old[0]:g}` 抛 ValueError 崩溃**(见 §2 P2-1)。真实库无此形态(REAL 列),但判定语义应为「空串=脏数据」而非崩溃
  - **边界 NULL**:NULL=缺口可补 ✓

### 1.2 manual 行保护 — PASS
双层保护:①循环内 `old[1]=='manual'` → skipped_manual 跳过(不调 _upsert);②`_upsert` SQL `ON CONFLICT ... WHERE daily_metric.source != 'manual'`(backfill_lianban.py:307),与 width_history.upsert_width 同款。
- 沙箱直测全模式:`only_if_null=True` + manual → 不写;覆盖模式 + manual → 不写(现库 9.0/manual 保持不变)✓
- **无旁路**:全脚本唯一写路径 = `_upsert`(backfill_lianban.py:257),唯一调用点,两模式下都带 `!= 'manual'` WHERE ✓
- caveat:见 §2 P2-2(manual+NULL 行的账实不符)

### 1.3 幂等 — PASS
- 沙箱实测:第一轮 planned_write=2(补 2 缺口),第二轮 planned_write=0 / skipped_existing=2 / 库行数不变 ✓
- `--only-if-null`(fill-gaps 默认)与普通模式行为差异:fill-gaps 第二轮零变更;覆盖模式第二轮会把非 manual 已有值重写一遍(updated_at 刷新,值不变)——覆盖模式本身需显式 `--overwrite`,属设计内。

### 1.4 F7 only_if_null 竞态加固 — PASS(闭环确认)
- 加固点 = `_upsert` when 子句:`fill_gaps_only=True` 时追加 `AND daily_metric.value IS NULL`(backfill_lianban.py:308-309)。
- 沙箱直测:读快照后他人已写非空值 → 本行 DO UPDATE WHERE value IS NULL 不命中 → 不覆盖 ✓;NULL 行 → 补 ✓;覆盖模式(only_if_null=False)有意放开 ✓。
- **覆盖所有写入路径**:唯一写入函数 `_upsert`,fill-gaps 模式必带 only_if_null=True,无第二写入路径,无旁路 ✓。

### 1.5 F1 翻页取满 — **PASS-with-caveat(见 §2 P1-1)**
- 逐页循环:`page=1` 取首页 → `pagination.pages` 翻到最后一页拼接(backfill_lianban.py:104-130)。
- 沙箱实测:pages=3(601 行,高连板 13 在尾页)→ 601 行全取、max=13 ✓;中途页失败 → 返回 None → 记 gap ✓;页数正确时取满无误。
- **caveat = 翻页停止条件只有 `pagination.pages` 一个**:无 `len(batch)<200` 末页兜底、无 `MAX_PAGES` 上限、无 `len(df) vs pagination.total` 对账机检(TRUNCATED 告警)。`fapi_fallback.fetch_zt_fallback`(#140 2026-09-30 合 main 的加固版)四重停止条件 + TRUNCATED 全都有 —— 本脚本是**第二份更弱的翻页实现**,实测 pages 缺失时静默截断 200 行、msg 还谎报 "200 rows(pages=1)"(真值 13 → 得出 1)。真实跑中 FAPI pages 字段可靠故 7 个普涨截断日全修正正确,但留档复用时此缺口会**静默写错更低的连板值**(比 gap 更难发现)。

### 1.6 失败安全 — PASS
- **单事务原子性实测**:沙箱 mock 中途抛 RuntimeError(第 3 日)→ 已写前 2 日 INSERT 未 commit,`finally: conn.close()` 回滚 → 库 0 行变更,无中间态 ✓(与清单 F8 文档声称一致)。
- 异常路径:网络/API 失败一律走 `_fetch_zt_with_retry` 重试 3 次后退化成 gap(记 reason),不抛、不写、不静默。
- WAL:默认连接走 app.db.get_conn(设 WAL + busy_timeout=30s);`--db` 直连不强制 WAL,但生产库本身已是 WAL 模式(模式持久化于库文件),无影响。
- caveat:单事务整段持写锁 ~20-40 分钟(逐日节流网络请求),期间其它写者 busy 排队——清单已用「23:00+ 安全窗口」纪律缓解(§2 P2-6)。

### 1.7 dry-run 与真写同一逻辑路径 — PASS(§5.4⑦ 同构)
- 写/不写判定完全在共享循环体内:`rows` 追加与跳过计数先执行,dry-run 仅短路 `_upsert` 调用(backfill_lianban.py:256-257)。planned_write/skipped_*/gap 计数不区分 dry-run 与真写。
- 沙箱实测:同一输入 dry-run planned_write=2 == 真写 planned_write=2;dry-run 前后库文件 md5 逐字节一致 ✓。
- 残余差异(dry-run 天然不含):dry-run 不执行 _upsert SQL,语法/约束问题只会在 --write 暴露——可接受。
- 辅助脚本注意:verify_lianban_fillgaps_zerotouch.py 重放 SQL 是**手抄第二份**(无 `AND value IS NULL`、不 import _upsert),目前与 _upsert 对齐,未来 _upsert 改动会静默漂移(§2 P2-5)。

### 1.8 生产隔离 — PASS-with-caveat
- 全仓 grep `backfill_lianban` 引用 = 脚本自身 + docs(无 scheduler/cron/timer/import 挂载),不会被误挂定时链 ✓。
- 防误跑护栏:`--write` 显式标志才真写(默认 dry-run),`--dry-run`/`--write` 互斥、`--fill-gaps-only`/`--overwrite` 互斥、--start 格式校验(全 CLI 沙箱实测 exit=2)✓。
- caveat:无 in-script 生产库确认/备份提示(§2 P2-7);导入 fapi_fallback 私有函数 `_api/_date_ms/_zt_df`(§2 P2-8)。
- 与既有 backfill(rzhb/lhb)无锁冲突:无文件锁,冲突仅 sqlite 写锁时序,busy_timeout 30s + 安全窗口纪律覆盖。

### 1.9 备份/恢复 — PASS(外部依赖,文档明确)
- 脚本自身**不内建备份**;备份 = 文档强制前置步骤(`docs/ops/lianban-prod-write-checklist.md` §三:SQLite 在线 backup API,而**非裸 cp**——WAL 安全,实测副本行数与源一致 + integrity_check)。
- 恢复路径明确:清单 §七 + 写库报告 §4(backup API 覆盖恢复 + 清 -wal/-shm + 无写入进程确认 + 不用重启服务)。
- 生产实跑已执行完整闭环(备份产物 `sentiment.db.bak-lianban-202610012304` 在位,integrity ok,回滚路径可执行)。

### 1.10 静默失败点 — 未发现致命,1 个 P2
- 无 `except: pass`:`_api`(fapi_fallback)吞异常返 None 属既有模块行为,上层以 gap 显式上报(记 reason + 汇总打印 + JSON 落盘),非静默。
- 忽略返回值:仅 `_upsert` 返回值未用(execute 失败会 raise → 非静默);`_fetch_zt_with_retry` 失败 → gap ✓。
- **P2-4:exit code 恒 0**(参数错除外):全量 1230 日 FAPI 挂掉也只记 gap 且 exit 0 —— 自动化挂链时静默,当前手动使用可接受(§2)。
- 空池(涨停真 0)→ 记 gap 不写 0,且 msg 声称"真0语义一致"与行为矛盾(§2 P2-3)。

## 2. 缺陷清单(按严重度)

### P0
无。

### P1
**P1-1 翻页停止条件单一,无末页兜底/上限/对账(可静默写错值)**
- 位置:`app/backfill_lianban.py` `_fetch_zt_all_pages`(L104-130)。
- 证据:沙箱 mock「pagination.pages 缺失」→ 只取 200 行,msg="200 rows(pages=1)" 无任何截断告警,max 从真 13 变 1;而 `fapi_fallback.fetch_zt_fallback`(L93-147,#140 2026-09-30 合 main)有四重停止条件(页数翻完/总量取满/`len(batch)<200` 末页兜底/MAx_PAGES=10 触顶)+ `len(df) vs total` 对账 TRUNCATED 告警。两处同源翻页逻辑已经分叉,本脚本是更弱版。
- 影响:>200 涨停的普涨日若 FAPI pages 字段缺失/不准 → **静默写更低的连板值**(比 gap 隐蔽,下游直接吃错数),20241008 单页 6 vs 真 13 即同款病灶的历史实例。
- 修复建议(一行级别):`_fetch_zt_all_pages` 直接改调 `fetch_zt_fallback("stock_zt_pool_em", date)`(同构复用,消灭第二份实现,§5.4⑦),或至少镜像四重停止条件 + TRUNCATED。
- trace:app/backfill_lianban.py L104-130;linkage:不满足(翻页是本次需求核心,弱实现=留隐患);verifier:见上 mock 复现;over_engineering:不适用(此条是加保险不是删代码,反向)。

### P2(全部登记,不阻断)
- **P2-1 已有值为空串/非数值 → 脚本崩溃**:`max_lianban` 判空串为已有值后,verbose 打印 `{old[0]:g}` 抛 ValueError(实测复现,L244,同款 L237/L254)。真实库 REAL 列无此形态,但应"跳过而非崩"。修法:`:g` 改宽容格式化或先判数值类型。
- **P2-2 manual+NULL 行账实不符**:manual 且 value IS NULL 的行(缺口形态)绕过了循环内 manual 检查(只在 `old is not None` 时触发),记入 planned_write 但被 SQL `!= 'manual'` 拦截不写 → 报告 planned_write 虚高 1(实测:planned_write=1、库仍 NULL/manual、skipped_manual=0)。数据安全,仅计数误导;修法:循环内 manual 判定改按 "date in existing 且 source=manual"或按键先查一遍。
- **P2-3 空池(涨停 0)记 gap 不写 0,注释与行为矛盾**:L127-129 注释称"与东财空=真0 语义一致",循环 L221-223 却记 gap。真 0 日永远留 gap、每次重跑都 retry;若下游期望 0 值则缺口残留。
- **P2-4 exit code 不反映 gap**:全量失败也 exit 0(gap 仅打印+JSON)。#132 同族病灶的弱形态,当前手动使用无碍;若未来挂自动化,需 `gap>0 → 非零退出` 或告警。
- **P2-5 辅助脚本手抄 _upsert SQL(drift 面)**:verify_lianban_fillgaps_zerotouch.py L50-55 与 sent_impact_lianban.py L34-42 各有一份 `WHERE source != 'manual'` 重放 SQL,不 import `_upsert` —— _upsert 未来加保护(如 P2-2 修法)这三处不会自动跟,与 §5.4⑦ 「复刻=第二份实现」同源。当前逐位对齐(verify 有 `len(rows)==planned_write` 断言兜底)。
- **P2-6 单事务持写锁全程(~20-40 分钟)**:原子性好但占用写锁;与生产定时器撞窗会互等(已有清单 §二.4 安全窗口纪律缓解,登记防复用者忘纪律)。
- **P2-7 无 in-script 生产护栏**:不校验目标库路径/不提示备份,`--write --db <默认生产库>` 即真写;依赖文档纪律(清单 §三强制备份)。留档复用时建议加 `--confirm` 或目标库存在性/备份提示。
- **P2-8 导入 fapi_fallback 私有函数**(`_api/_date_ms/_zt_df`):fapi_fallback 重构内部实现会破坏本脚本(import 断链即静默失败类型)。

## 3. 审查方法说明

- 沙箱:`git archive 76349cde1` 导出至 /tmp/lianban-rv-src,venv 运行,`_api`/calendar 全 mock,13 个场景(只补缺口/NULL 补齐/0 值/空串/manual 双闸/manual NULL/幂等/dry-run 同路径与 md5 零写/ST 排除/翻页取满/pages 缺失截断/中途页失败/单事务回滚/CLI 参数)。
- 未重现:空池→gap 行为(L221)、真实 FAPI 网络调用(沙箱 CLI 一次自然触发,只读)。
- 依据文档:three 配套文档与 fapi_fallback #140 加固实现比对。
- 已滤低分项:1 条(空串判定属 pre-existing 数据形态,但破坏于本脚本打印路径,保留为 P2-1);`--db` 不设 WAL 为 nitpick 不报。

## 4. 结论复述

- 判定:**PASS-with-caveat**。
- 必改前项:P1-1(翻页兜底,一行调用 `fetch_zt_fallback` 即可);P2-1(空串崩溃,`:g` 宽容化,一行)。
- 其余 P2 登记作 follow-up,不阻断留档。
