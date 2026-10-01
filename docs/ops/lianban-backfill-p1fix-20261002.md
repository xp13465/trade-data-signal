# 连板回补脚本 P1-1 修复报告(2026-10-02)

> 审查来源:`docs/ops/lianban-backfill-review-20261002.md`(PASS-with-caveat,唯一合入前必改项 = P1-1)。
> 结论:**P1-1 已修(走方案①:消灭第二份翻页实现,复用 #140 加固版)**,自测 4 项 + 2 项回归全 PASS,修前/修后已取满场景 dry-run 输出**逐位一致**。

---

## 1. 修什么:P1-1 翻页停止条件单一

- 位置:`app/backfill_lianban.py` 原 `_fetch_zt_all_pages`(旧 L104-130)。
- 病灶:**只按 `pagination.pages` 翻页**,无末页兜底(`len(batch)<200`)/无 `MAX_PAGES` 上限/无 `len(df) vs total` 对账。
- 审查实测:响应缺 `pages` 字段 → **静默截断 200 行、msg 谎报 "200 rows(pages=1)"、连板 max 真 13 变 1**——写更低的值比留 gap 更隐蔽(下游直接吃错数)。
- 同源翻页逻辑在 `app/collector/fapi_fallback.py::fetch_zt_fallback` 已是 **#140 加固版**(2026-09-30 合 main,四重停止条件),backfill 这份是**更弱的第二份实现**。

## 2. 怎么修:走方案①(消灭第二份实现,§5.4⑦ 同构对账精神)

- **改法(一行级)**:`_fetch_zt_all_pages` 直接改调 `fetch_zt_fallback("stock_zt_pool_em", date)`,不再持有自己的翻页循环。
- import 同步:`from .collector.fapi_fallback import _api, _date_ms, _zt_df` → `from .collector.fapi_fallback import fetch_zt_fallback`(原私有函数 import 全部清掉,顺带消除审查 P2-8 登记的「导入私有函数」drift 面——这是走①的必然结果,非额外顺手改)。
- **为什么走①(对接核对)**:两者返回结构一致 `(df|None, msg)`、df 含东财兼容列 `名称/连板数`;ST 过滤在 backfill 侧 `max_lianban_ex_st` 做(排除后才是东财可比口径),`fetch_zt_fallback` 不做 ST 过滤、只负责取满,职责不冲突;调用方 `_fetch_zt_with_retry` 期望 `(df|None, msg)` 原样对接。空池语义:`fetch_zt_fallback` total=0 返回空 df + msg `empty(真0)`,backfill 主循环 `len(df)==0` 记 gap,语义一致。
- **不动的**:`max_lianban_ex_st`(ST 排除)/ `_upsert`(写库保护)/ dry-run 与真写路径语义 / CLI —— 全部不动,只换取数实现。

## 3. 改动前后对照

| 项 | 改前(旧 `_fetch_zt_all_pages`) | 改后(复用 `fetch_zt_fallback`) |
|---|---|---|
| 翻页停止条件 | 仅 `pagination.pages` 一个 | 四重:#140 按 pages 翻页 / `len(batch)<200` 末页兜底 / `MAX_PAGES=10` 安全上限 / `len(df) vs total` 对账 TRUNCATED 告警 |
| pages 字段缺失 | 静默截断 200 行,msg 谎报 "200 rows(pages=1)" | 末页兜底翻满(实测取满 601/401 行);若 total=0 显式 `empty(真0)` 记 gap |
| 超过 MAX_PAGES | 无上限,服务端异常可无限翻页 | 触顶停,对账 TRUNCATED 告警不静默 |
| 取满不匹配 total | 无对账 | `msg += "; TRUNCATED total=X got=Y"` 显式告警 |
| 第二份实现 | 有(与 fapi_fallback 分叉) | 无(单实现,fapi_fallback 为唯一权威翻页) |

## 4. 自测表(沙箱全 mock,未碰任何生产库/本机 data/)

| # | 场景 | 实测结果(修后) | PASS |
|---|---|---|---|
| 1 | **pagination.pages 缺失**(total=601,真 13 在尾页) | 翻页取满 601 行,`max=13.0`;改前同场景 `max=1.0`(静默截断)。不再静默截断 ✓ | ✅ |
| 2 | 正常多页(pages=3、601 行) | 取满 601 行,`max=13.0`(两日均 13.0) | ✅ |
| 3 | 幂等回归(/tmp 沙箱库真写一遍再 dry-run) | 第一遍真写 `planned_write=2`;第二遍 dry-run `planned_write=0 / skipped_existing=2 / gap=0`,库内实际仅 2 行无重复 | ✅ |
| 4 | `python3 -m py_compile` + 修前/修后逐位一致 | py_compile PASS;综合场景(普涨日 711 行+已有值跳过)修前/修后 dry-run 输出 **diff 为空**:`planned_write=1 / skipped_existing=1 / skipped_manual=0 / gap_days=0 / rows=[[20241008,13.0]] / gaps=[] / overlap_written=0 / increment=[20241008]` 逐位一致 | ✅ |
| 回归 | empty(真0, total=0) | 显式记 gap 2 天,`planned_write=0`,reason=`FAPI 涨停池空(真0或当日无数据): fapi limit-up-pool empty(真0) date=...`,不静默 | ✅ |
| 回归 | pages 缺失但末页不满 200(末页兜底) | 翻满 401 行,`max=11.0`(改前只取 200 行 max=1) | ✅ |

> 自测 4 口径说明:改前版本用 `git worktree add --detach HEAD` 检出同 commit 代码跑同一 mock 场景,diff 逐位一致后已 `git worktree remove --force` 清理;全程只写 `/tmp/*.db` 沙箱库,未碰 `/home/ubuntu/...` 生产库与本机 `data/`。

## 5. 复现段

```bash
# 1) py_compile
/Users/linhuichen/code/trade/.venv/bin/python -m py_compile app/backfill_lianban.py

# 2) 自测 1/2/回归(pages 缺失 / pages=3 / empty / 末页兜底):mock _api 返回构造响应,
#    mock calendar.trading_days_between 返回固定日期,跑 backfill_lianban(dry_run=True)
#    断言取满 max=13、empty 记 gap。
#    测试脚本见本次 commit 说明(沙箱 /tmp,不入 git)。

# 3) 自测 3 幂等:对 /tmp/lianban-p1fix-test/idem.db
#    第一遍 dry_run=False(planned_write=2)→ 第二遍 dry_run=True(planned_write=0/skipped_existing=2)

# 4) 自测 4 逐位一致:git worktree add --detach /tmp/lianban-before-wt HEAD(改前)
#    → 同一 mock 场景跑 gen_output.py → diff out_before.json out_after.json 为空
#    → git worktree remove --force /tmp/lianban-before-wt
```

复现所需文件:仅 `app/backfill_lianban.py`(本次改动)+ mock 场景脚本(评审期 `/tmp/lianban-p1fix-test/`,临时不入 git);外部依赖 `app/collector/fapi_fallback.py`(#140 加固版,已在 main)。

## 6. 范围与边界

- **只修 P1-1**。审查列出的 P2(P2-1~P2-8)全部**不修**,已在审查报告登记台账,按 follow-up 处理。
- 未动 dry-run / 真写路径语义(同一共享循环体,dry-run 仅短路 `_upsert`);未动 `max_lianban_ex_st` / `_upsert` / CLI。
- 走①对既有行为影响:`fetch_zt_fallback` 失败 msg 不带 `date=`(如 `fapi limit-up-pool page2/3 unavailable`),但 gap 记录里 `date` 单独存、reason 不带日期不丢信息;成功场景 msg 不进库、不改变任何写入值。
- **生产无影响确认**:本脚本未被 scheduler/cron/timer 挂载(审查 §1.8 已证),本次仅代码健壮性,不触发线上任何行为变化。
