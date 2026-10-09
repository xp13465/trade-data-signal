# #238 fapi 续审报告(只审本次增量)

- 审查者:reviewer(只读) · 日期 2026-10-09 · 上一轮报告:/tmp/fapi-review-20261009.md(旧 tip 69b718ced,有条件 merge)
- 新 tip:**a0867e97b** · worktree:/Users/linhuichen/code/trade/.claude/worktrees/agent-af740ef45d60d8df2/
- **总判:可 merge**(5/5 PASS,必须修 0;仅 1 条措辞精度注记 + 1 条残余说明,均不阻断)

## 点1 ①过检才写=零写入 — PASS

静态(逐行核调用与副作用顺序):
- 数据写路径唯一 = `_flush`(executemany + commit,L475 附近);`_flush` 只作 pass2 的 `on_rows` 回调;
  pass2(`process_parquet` L390)只在 `scan_parquet` 全过后才执行(`stats = scan_parquet(...)` 在前,不过即 raise)。
- `run()`:`conn = None`(L467)起,连接**首写才开**;`finally: if conn is not None: conn.close()` 异常时跳过 ⇒ pass1 raise 零写。
- 早返回/异常分支逐一核:dry_run 在开写连接前 return;无其他写路径(全文 grep `executemany|commit` 仅 `_flush` + `init_db` 建表 DDL,后者为既有代码)。

动态(决定性证据,自建 red-first harness /tmp/redfirst238/harness.py,importlib 同载新旧两版,坏 dump=真实切片+末尾追加重复行):
- 修复前 69b718ced:`process_parquet(bs=7)` raise 但回调 **seen=121 行**;full `run()` raise 但库 **db_rows=120**(坏行真落库,121 行 upsert 去重成 120 键)⇒ Finding 1 精确复现。
- 修复后 a0867e97b:`seen=0`、`db_rows=0` ⇒ 零写入端到端成立。

注记(非阻断,措辞精度):`init_db()`(L445)/`db_latest_date()`(L447)在 pass1 前各开过一次连接(含 WAL pragma + 建表 DDL commit),但:(a) 与 #238 前旧版顺序完全一致(旧 L259/L261 同位置);(b) 只碰 schema / 只读,零数据行;(c) 代码注释限定语是"**写**连接",语义正确。文档 §1 若被字面理解成"过检前任何连接都不发生"偏宽,建议限定为"数据写连接首写才开"。不构成 Finding 1 残留。

## 点2 两遍扫描口径等价 + 列裁剪/内存不退化 — PASS

口径等价(旧守卫 verbatim,见 /tmp/old_fapi_43cb3e804.py L274-281):
- dup:旧 `df.duplicated(subset=["thscode","date_ms"]).sum()`;新 `Σ(len(dm)-len(np.unique(dm)))`(按组)。
  连续分组前提下达同值:重复键必同 thscode ⇒ 必同组;非连续分组已由 `_emit` 先 raise。计数语义同为"多余出现次数"。
- amt_ok:旧 `(turnover.abs()>volume.abs()).mean() < 0.9`;新 `np.sum(...)/total < 0.9`(total=输入行数,`total and` 护空)。
- 顺序一致(先 dup 后 amt)、报错文案逐字一致 ⇒ 守卫语义未变。

列裁剪 + 内存实测:
- `scan_parquet` 单跑真实 10 年 dump(10,316,588 行):**peak 209MB / 1.5s**,dup=0,amt_ok=10,316,021(与文档 210MB 吻合;`_GUARD_COLS` 无 OHLC 大列,裁剪真实生效)。
- 两遍全流程(`process_parquet` 流式)peak **300MB**(基线 11MB),与 implementer 298/299/300 一致;较单遍 290MB 仅 +10MB(~3%),仍 <300 目标(容差 320);pytest 断言 `s_peak*3 < l_peak` 兜量级降幅。
- 信息(非问题):文档"full 路径 ≈+20s"偏保守,实测 pass1 仅 1.5s(列裁剪+页缓存)。

## 点3 ③黄金 oracle 独立性 — PASS

- 43cb3e804 确为 pre-change:它是 origin/main 祖先;blob 内含 `STALE_DAYS=8`(L60)、物化版 `map_frame`(L179)、`upsert_rows`(L217),无任何流式符号;blob md5 = **682e6b588b82833d8f00ce825792ffaf** == `LEGACY_MD5`(33c6bace2 与 origin/main 同值,gen 注释"三处一致"属实)。
- md5 门控实际作用(正/负双实测):
  · 正:默认 ref `--check` → "OK: …可由 43cb3e804 旧实现复算(rows=120)"。
  · 负:错 ref(aeadb9047,中间态)→ 被拒:"旧实现 md5 不符(闸门):期望 682e…,实得 4a7b…。拒绝生成(防产出假黄金)"⇒ 门控有真实判别力;负用例后黄金文件零改动(git status 空)⇒ `--check` 只读且不误写。
- 自我实现问题(上轮遗留):黄金 = **旧实现(独立代码)** 输出,独立于当前 `_map_group` ⇒ 独立锚已建立。残留:`test_streaming_equals_reference_oracle` 仍与实现共享 `_map_group`,但其覆盖面=分组/分批管道;端到端映射语义已由黄金测试(bs 1/7/13/120/999 + map_frame 对照)兜住 ⇒ **影响面≈0**。黄金内容抽查:120 行 / 0 NaN / 行0 合理(000001.SZ 20161010 OHLC 齐全,turnover 列 None)。

## 点4 分支 diff 无夹带 + rebase 内容差异 — PASS

- 分支文件(MB..tip)恰好 9 个,全部预期:app/collector/fapi_daily.py、docs/fapi/×2、docs/ops/fapi-daily-oom-fix-20261009.md、scripts/tests/fapi_oom_mem_probe.py、fixtures/238/expected_rows.json、fixtures/238/sample.parquet、scripts/tests/gen_fapi_golden_238.py、scripts/tests/test_fapi_oom_fix_20261009.py。无夹带。
- MB == origin/main tip(33c6bace2)⇒ 无交叉,可 fast-forward。
- 内容差异 69b718ced→a0867e97b = 3 个 main 前进的报告文档(fapi-daily-oom-fix-review / host-hardening / host-hardening-verify,与分支不相交)+ 7 个修复文件;fapi_daily.py 修复 diff 尾核到 `_flush`/`finally` 为止,除既有修复外无其他改动;remote `origin/feat` == 本地 tip;worktree `git status --porcelain` 空。
- 假设声明:本地 origin/main ref 未重拉(fetch 属 git 写,审查禁),以本地 ref 为准。
- 两份历史文档注记:逐字核,fapi-integration-plan-20260901.md(L110 后)+ fapi-p0-implementation-20260902.md(L38 后)各 +1 行"⚠️ 注记(2026-10-09)…",原文保留、指向 #238 + oom-fix 文档、口径(>10 交易日)与代码一致。

## 点5 全量 pytest 复跑 — PASS

- 自跑:**411 passed / 2 skipped in 86.86s**;先断言 `fd.__file__` 在 worktree(IN_WORKTREE=True,防 symlink 假绿);算术自洽 400 − 16 + 27 = 411。
- 附带复核:`upsert_rows` 在 fapi_daily.py 全文零命中(其余命中=baostock/mootdx 各自模块的同名函数,非本模块);内存探针文件与 69b718ced 逐位一致(diff 空)+ 执行前静态复核只读(无 conn/sqlite/网络/open 调用)。

## 必须修清单

- 无。

## 建议(可选,非阻断)

1. 措辞:文档 §1/注释"过检前连 WAL pragma 都不发生"建议限定为"数据**写**连接首写才开"(init_db/db_latest_date 在前,与旧版一致,仅 schema/读)。
2. 残余说明留档:reference-oracle 测试共享 `_map_group` 的覆盖面边界(已由黄金独立锚兜底)。

## 交主控收尾(不属于本分支修复)

- pending-features-index #238 状态列刷新(§23.12-1)归主控 merge 收尾时做。
- 本报告不 commit;red-first harness 与内存测量脚本在 /tmp,不随分支。
