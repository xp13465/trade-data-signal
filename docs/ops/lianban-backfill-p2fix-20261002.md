# 连板回补独立审查 P2 残留收尾修复(2026-10-02)

> 收尾 `docs/ops/lianban-backfill-review-20261002.md` 的 P2 残留。P1-1 已修并合 main(b09a2f62f)。
> 本批修 6 条(P2-1/2/3/4/5/7),不修 2 条(P2-6/P2-8,理由见末)。
> 全程只碰 /tmp 沙箱库,不碰生产库、本机 data/、云上。

## 逐条改法 / 前后对照 / 自测值 / 为何这么改

### P2-1 崩溃:verbose 打印 `{old[0]:g}` 遇空串/非数值抛 ValueError

- **改法**:新增 `_fmt(v)` 帮助函数——bool 原样、数值 `f"{v:g}"`、其余 `str(v)` 兜底;`_existing_map` 三处打印(L237/L244/L254 同款)与对账 mismatch 打印全改用 `_fmt`。对账比较改 `_to_float(v)` 宽容转换(None→None、非数值→None、数值 float),`abs(a-b)<1e-9` 比较前双方都过 `_to_float`。
- **为何这么改**:`{v:g}` 只吃数值,库内可能残留脏值(空串/非数值),打印即崩是「日志打崩流程」的坏味道;打印本就不该抛异常。对账比较对非数值宽容(视为不相等但不崩)。
- **前后对照**:
  - 修前:已有值 `''`(空串)→ `ValueError: cannot format ''` 崩溃。
  - 修后:`_fmt('')` → `''` 原样打印「现库=(source=akshare) 新值=3」不崩;非数值 `'abc'`(source=manual)→ `_fmt('abc')` → `'abc'` 原样打印「manual跳过」不崩。
- **自测值**:
  - 空串已有值 dry-run verbose:`P2-1 PASS:空串已有值不崩,{'planned_write': 1, 'skipped_existing': 1}`。
  - 非数值 manual dry-run verbose:`P2-1b PASS:非数值 manual 不崩,{'planned_write': 1, 'skipped_manual': 1}`。

### P2-2 账实不符:manual+NULL 行绕开循环内 manual 检查被计入 planned_write

- **改法**:新增 `_source_map(conn, start, end)`——与 `_existing_map` 同查询但**含 value IS NULL 行**的 date→source 映射;循环内 manual 判定从 `old is not None and old[1]=='manual'` 改为 `src_map.get(d)=='manual'`,覆盖 manual+NULL 行;匹配的计入 `skipped_manual` 而非 `planned_write`。
- **为何这么改**:`_existing_map` 只取 value IS NOT NULL 行 → manual+NULL 行 `old=None` → 原 manual 检查不触发 → 计 planned_write,但被 SQL `WHERE source != 'manual'` 拦截。`planned_write` 是「实际会写」的承诺数,必须与写入口径一致;账实不符会让对账脚本(如 verify_zerotouch 的守恒 assert)失准。独立 `_source_map` 是仅有的正确判定源(含 NULL 行才不漏)。
- **前后对照**(4 日沙箱:20210901 已有、20210902 增量、20210903 manual+NULL、20210904 空池):
  - 修前:`planned_write=2` 含 20210903(manual+NULL)误计,`skipped_manual=0`。
  - 修后:`planned_write=2`(20210902 增量 + 20210904 真0写0),`skipped_manual=1`(20210903)。
- **自测值**:写库模式 `write1: {'planned_write': 2, 'skipped_existing': 1, 'skipped_manual': 1, 'gap_days': 0}`;写后库行 `[20210901=5.0 akshare, 20210902=4.0 fapi, 20210903=NULL manual(未动), 20210904=0.0 fapi]`。

### P2-3 真 0 语义矛盾:空池被记 gap,注释却写「真 0 语义一致」

- **改法**:循环内 `len(df)==0` 分支改为写 0——`value, st_cnt, total = 0.0, 0, 0`(写 0.0,source=fapi),不再记 gap。`_fetch_zt_all_pages` docstring 补空池语义说明。
- **判据(先定哪个对,再改)**:
  1. `app/collector/fapi_fallback.py`:`total==0` → 返回空 df + msg 含 `"empty(真0)"`,即**服务端显式声明当天涨停池为真 0**;请求失败返回 None 是另一条路径。
  2. 故 `len(df)==0` 的唯一合法含义 = 当天涨停真 0,东财可比口径下连板数就是 0(东财空池=0 语义一致)。
  3. 原记 gap 的后果:该日永久 retry 空转(缺口永补不上),下游 sentiment 的 lianban 分项永远缺失——这是把「合法真 0」当成「抓取失败」处理,错。
  - 结论:**写 0 是对的**,改代码不改注释。
- **对已写库数据影响**:无。已写库 1154 天都是 fapi 成功值,空池日原本没写(gap);本批修复后若重跑,空池日会补写 0.0,这是正确收敛,不与现有数据冲突。
- **前后对照**:
  - 修前:20210904 空池 → `gap_days=1`,不写。
  - 修后:20210904 空池 → 写 0.0,`gap_days=0`。
- **自测值**:`db_rows_after_write1` 含 `('20210904', 0.0, 'fapi')`;`gap_days=0`。

### P2-4 静默退出:exit code 恒 0,全量失败也静默

- **改法**:main() 返回分级——参数错误 rc=2;P2-7 生产护栏拦截 rc=3;有 gap_days 且模式已尽力仍留缺口 → rc=1;正常 rc=0。dry-run 正常路径仍 rc=0。
- **为何这么改**:恒 0 退出让脚本在定时/CI 链路里全量失败也「绿」,等于没监控。分级让调用方能区分「参数错/护栏拦/有缺口/成功」;dry-run 成功(即便有 gap 也不视为失败场景,但留 gap 若属异常可被外层捕捉)不破坏现有手动用法。
- **前后对照**:
  - 修前:`python -m app.backfill_lianban --start abc` rc=0(参数错也 0)。
  - 修后:参数错 rc=2;护栏拦 rc=3;dry-run 正常 rc=0。
- **自测值**:`P2-4a 参数错 rc: 2`。dry-run 正常路径 rc=0(driver 全程 rc=0)。

### P2-5 手抄 SQL 漂移:两个辅助脚本手抄 _upsert 而非 import

- **改法**:
  - `docs/scripts/verify_lianban_fillgaps_zerotouch.py`:顶部加仓库根入 sys.path(`_REPO = Path(__file__).resolve().parents[2]`),`from app.backfill_lianban import _upsert, METRIC_ID`(保留 `METRIC = METRIC_ID` 别名兼容),重放块逐行 `_upsert(conn, r["date"], float(r["value"]))`,删手抄 SQL。用法更新为 venv python + 仓库根运行。
  - `docs/scripts/sent_impact_lianban.py`:顶部 `from app.backfill_lianban import _upsert`;`inject_lianban()` 逐行 `_upsert(conn, r["date"], float(r["value"]))`,n=len(rows),删手抄 executemany SQL。
- **为何这么改**:§5.4⑦——复刻脚本=第二份实现,前端/主实现改逻辑副本不自动跟、静默漂移是必然。`_upsert` 内嵌 manual 保护 + only_if_null 竞态加固,import 复用后两脚本自动跟随主实现,永不漂移。
- **前后对照**:修前两脚本各自手抄 `INSERT ... ON CONFLICT(date,metric_id) DO UPDATE SET ... WHERE source != 'manual'`;修后共用 `app.backfill_lianban._upsert`。
- **自测值**(全 mock 4 日沙箱):
  - verify 脚本:`计划写入行数=2 | src total rows=3 | dst total rows=5 | added_rows=2(全 a_width_max_lianban) | removed_rows=0 | changed_rows=0 | 结果: PASS 除新增缺口行外全库逐行零变化`,rc=0。
  - sent_impact `inject_lianban`:注入 n=3,库现状 `[20210901=5.0 akshare, 20210902=4.0 fapi, 20210903=NULL manual(保护生效未覆盖), 20210904=0.0 fapi]`,PASS。
  - 顺带修:verify 脚本对比段 `abs(a-b)` 遇 value=None 行 TypeError(顺带加 `_vals_equal` 宽容比较,None==None、None≠数值)。

### P2-7 生产护栏缺失:--write --db 默认生产库路径即真写

- **改法**:main() 加 `--confirm-prod` 参数 + 护栏——`args.write and _target_is_prod(args.db)` 且无 `--confirm-prod` / 无环境变量 `LIANBAN_CONFIRM_PROD=1` → stderr 提示 + return 3。`_target_is_prod` 判定:db=None(默认连生产库)→ True;realpath 与 `app.db.DB_PATH` 相等 → True;**新增云上主库常量 `_CLOUD_PROD_DB = "/home/ubuntu/code/trade-data/data/sentiment.db"`(与 checklist 钉死执行目标一致)realpath 相等 → True**(云上 app.db.DB_PATH 经 symlink 可能解析到旧镜像 trade-data-signal/data,realpath 与主库不等,须显式登记)。其余沙箱/副本 → False。
- **为何这么改**:留档复用者凭文档纪律误写生产库,靠人脑纪律兜底不可靠;in-script 强制二次确认把「误写」成本提到零。云上路径显式登记是因为护栏要覆盖 checklist 真实执行路径,不能只防本机。
- **正确用法**(文档正常写库流程已同步 `docs/ops/lianban-prod-write-checklist.md` 第五节):
  ```bash
  cd /home/ubuntu/code/trade-data
  /home/ubuntu/code/trade-data/.venv/bin/python -m app.backfill_lianban \
    --start 20210901 --end 20260929 --db /home/ubuntu/code/trade-data/data/sentiment.db --write --confirm-prod \
    2>&1 | tee .../lianban_backfill_run.log
  ```
  dry-run 复核命令**不需要** `--confirm-prod`(护栏只管 `--write`)。
- **前后对照**:
  - 修前:`--write` 不带 `--db` → 默认连本机生产库真写,无确认。
  - 修后:`--write` 不带 `--db` → rc=3 拦截;显式沙箱 `--db` → 放行;加 `--confirm-prod` → 放行。
- **自测值**:
  - CLI:`P2-7a 未指定--db + --write rc: 3(expect 3)`;`P2-7b 加 --confirm-prod rc: 0`;`P2-7c 显式沙箱 --db + --write rc: 0(非3)`。
  - `_target_is_prod` 四判:`None→True`、`云上主库→True`、`本机DB_PATH→True`、`沙箱→False`,全 PASS。

## 逐位对账:修前 vs 修后 dry-run 输出差异

修前基线(修前 driver,4 日沙箱同数据):`planned_write=2 | skipped_existing=1 | skipped_manual=0 | gap_days=1`。
修后:`planned_write=2 | skipped_existing=1 | skipped_manual=1 | gap_days=0`。

**差异 2 项,均为预期内行为改变(非静默)**:

| 项 | 修前 | 修后 | 原因 | 是否预期 |
|---|---|---|---|---|
| 20210903(manual+NULL) | 计入 planned_write(实际被 SQL 拦,账实不符) | 计入 skipped_manual | P2-2 计数口径对齐实际写入口径 | 预期 |
| 20210904(空池) | gap_days=1,不写 | 写 0.0(fapi),gap_days=0 | P2-3 空池真0语义,写 0 而非记 gap | 预期 |

其余(20210901 已有值跳过、20210902 增量、skipped_existing 数、4 日交易日数)逐位一致,无其他差异。

## 不修项(P2-6 / P2-8)

- **P2-6(单事务持写锁 20~40 分钟)**:设计权衡,非缺陷——单事务=原子,中途 Ctrl-C/SIGKILL 零落库,已有「安全窗口 23:00 后 / 周末休市」纪律 + checklist §五 F8 说明。写锁期间拒绝其他写连接是 SQLite 正常行为,非脚本可改进点;拆多事务会失去原子性,得不偿失。
- **P2-8(fapi_fallback 私有函数 import)**:已随 P1-1 修复消除(独立审查 P2 定义取自旧版;P1-1 合 main b09a2f62f 后不再 import 私有函数)。

## 自测命令汇总

```bash
/Users/linhuichen/code/trade/.venv/bin/python -m py_compile \
  app/backfill_lianban.py docs/scripts/verify_lianban_fillgaps_zerotouch.py docs/scripts/sent_impact_lianban.py
# → PY_COMPILE_OK(3 文件)

/Users/linhuichen/code/trade/.venv/bin/python /tmp/lianban-p2/driver_write.py   # 写库+幂等
# write1: {'planned_write': 2, 'skipped_existing': 1, 'skipped_manual': 1, 'gap_days': 0}
# db_rows_after_write1: [('20210901',5.0,'akshare'),('20210902',4.0,'fapi'),('20210903',None,'manual'),('20210904',0.0,'fapi')]
# idempotent-dryrun: {'planned_write': 0, 'skipped_existing': 3, 'skipped_manual': 1, 'gap_days': 0}   # 幂等 PASS

/Users/linhuichen/code/trade/.venv/bin/python /tmp/lianban-p2/driver_edge.py    # P2-1/P2-4/P2-7
# P2-1/P2-1b PASS;P2-4a rc=2;P2-7a rc=3 / P2-7b rc=0 / P2-7c rc=0

/Users/linhuichen/code/trade/.venv/bin/python /tmp/lianban-p2/p25_test.py       # P2-5 两脚本实跑
# verify: PASS(added=2 全 lianban,removed=0,changed=0);sent_impact: PASS(manual 保护生效)

/Users/linhuichen/code/trade/.venv/bin/python -c "from app.backfill_lianban import _target_is_prod; ..."
# None→True 云上主库→True 本机DB_PATH→True 沙箱→False,全 PASS
```

## 文件清单

- `app/backfill_lianban.py`(P2-1/2/3/4/7)
- `docs/scripts/verify_lianban_fillgaps_zerotouch.py`(P2-5 + NULL 值对比宽容)
- `docs/scripts/sent_impact_lianban.py`(P2-5)
- `docs/ops/lianban-prod-write-checklist.md`(P2-7 写库命令补 `--confirm-prod`)
