# etf_daily.etf_name 写入契约缺失根因与防复发(2026-11-07)

## 问题
163109(申万菱信深证成份指数(LOF)A, DB 全称; board_etf_map.json 短名=申万深成LOF) 的
20261021–20261106 共 13 行已补 OHLC+NAV, 但 etf_name 全为 NULL;
真实价格加载函数 `scripts/signal_kelly_backtest.py::_batch_load_etf_prices` 的 SQL 含
`accum_nav IS NOT NULL AND etf_name <> etf_code`, NULL 不满足该条件 → 11-04/05/06 不进入
价格映射, 加载器仍停在 20261020。全表 NULL etf_name 共 19 行(13 条 163109 + 6 条老数据)。

## 根因(函数名锚点, 行号易漂移以代码符号为准)
- **直接来源**: 临时脚本 `/tmp/backfill_163109.py`(未提交)调用 `fetch_etf_ohlc()`(
  `app/collector/etf_national_team.py::fetch_etf_ohlc`, 返回 dict 只含
  date/etf_code/open/close/high/low/amount, **不返 etf_name**)后, 按 fields=`["etf_name",...]`
  upsert, 未在 row 上设 etf_name → `_upsert_daily`(`app/collector/etf_national_team.py::_upsert_daily`)
  写入 etf_name=NULL。
- **契约缺陷(根因, 非单脚本)**: `_upsert_daily` ON CONFLICT 裸赋值
  `etf_name=excluded.etf_name`, **无 NULL/空串/code 占位保护** → 任何调用方漏设 etf_name
  即把已有真实名覆盖成 NULL。对比 `scripts/backfill_etf_daily.py::upsert_etf_daily` 已有
  `COALESCE(NULLIF(etf_daily.etf_name,''),excluded.etf_name)` 保护, 主 `_upsert_daily` 缺这层。
- **同类潜在遗漏**: `scripts/export_etf_score_list.py::_compute_volatility` 补采分支的
  `etf_name = name_row[0] if name_row else code` 的 `else code` 兜底把 code 当 name 写入
  (占位行被加载器 `etf_name<>etf_code` 过滤);
  `_board_etf_map_lof_codes`(`app/collector/etf_national_team.py::_board_etf_map_lof_codes`)
  的 `name = ... or code` 写库占位。

## 写入路径审计清单(fields 含 etf_name 的 _upsert_daily 调用, 函数名锚点)
| 调用点(函数) | 路径 | 是否设真实名 | 本次 NULL 关联 |
|---|---|---|---|
| pipeline_daily | 每日 OHLC 采集 | 是(r["etf_name"]=universe name) | 否(生产正常) |
| pipeline_intraday_close | 收盘 close 采集 | 是(ETF_LIST name) | 否 |
| pipeline_intraday_realtime | 实时市价 | 是(ETF_BY_CODE name) | 否 |
| pipeline_backfill | 全量回填 | 是(worker `_fetch_one_backfill_worker` 设 name) | 否 |
| update_accum_nav | NAV 补齐 | fields=["accum_nav"] 不含 etf_name | 安全 |
| export_etf_score_list::_fetch_and_upsert_ohlc | 动态补采 | 是(caller 传 name) | 取决于 name 来源 |
| export_etf_score_list::_compute_volatility 补采 | 历史补采 | **else code 兜底(已修)** | 同类潜在 |
| 临时脚本 backfill_163109.py | fetch_etf_ohlc 直调 | **否 → NULL(本次直接来源)** | **是** |

fetch_etf_ohlc 消费点(etf_national_team `_fetch_one_ohlc_worker`/`_fetch_one_backfill_worker`/
`pipeline_intraday_close` probe, fetchers `fetch_etf_ohlc` 包装, multisource,
export_etf_score_list `_fetch_and_upsert_ohlc`/`_compute_volatility`)均不返 etf_name,
名称由调用方注入。

## 契约规则(唯一解析顺序, 含 F1 新行闭合)
前置规范化(每行 INSERT 前, 当 fields 含 etf_name):
1. 调用方传入的真实名称(非 NULL/非空串/非与 etf_code 同值占位) → 用它
2. 调用方传入 None/空串/缺失 → 解析: DB 该 code 已有非占位真实名 > board_etf_map.json 权威名
   > 都无则用 **etf_code 作显式占位哨兵**(非 NULL, 去重 warning 一次)。新行不再产生 NULL。
3. 调用方明确传入 etf_name=etf_code(主动占位哨兵, 如盘中假数据) → **保持原样**, 绝不用
   真实名替换(否则把假数据洗成真数据, 破坏 `etf_name<>etf_code` 防占位保护)。

ON CONFLICT 保护: 调用方真实名 > DB 已有真实名 > (DB 非空则 DB 原值, 否则 excluded.etf_code
占位) — 两值都无效也不产生 NULL。

## 修复(本分支 feat/signal-gap-name-contract-20261107)
1. **`_upsert_daily` 前置规范化 + ON CONFLICT CASE 保护**(单点, 所有 caller 自动受益):
   fields 含 etf_name 时每行前置规范化(规则 1-3) + ON CONFLICT CASE(真实名 > DB 真实名 >
   不产生 NULL)。新行 INSERT 不再产生 NULL(闭合 F1: 旧版只护 ON CONFLICT, 新行 None 仍写 NULL)。
2. **新增 `_resolve_etf_name_authoritative(code)`**: 从 board_etf_map.json 解析权威名(懒加载
   索引缓存, 无则返 None); `_resolve_name_for_upsert(conn, code)` 按 code 缓存(DB 名 > 权威名,
   1.5M 行回填每 code 仅一次 SELECT + 一次查表)。
3. **`export_etf_score_list._compute_volatility` 补采 else code 收紧**: 改为 DB 已有名 >
   board_etf_map 权威名; 始终含 etf_name in fields, None 交给 `_upsert_daily` 前置规范化兜底。
4. **`_board_etf_map_lof_codes` `or code` 收紧**: board_etf_map 无 name 时返 None(写库不占位)。

## 测试证据
- 新测试 `scripts/tests/test_signal_gap_name_contract_20261107.py`(11 passed):
  - 直接调用 `_batch_load_etf_prices`(monkeypatch 临时 DB, 不复制 SQL):
    A 真实名行进映射 / B etf_name=code 占位仍被排除 / C NULL 行仍被排除 / D 混合只真实名进映射
  - 直接调用 `_upsert_daily` 契约验证: NULL/空串/code 占位不覆盖已有真实名 / 真实名覆盖占位
  - F1 闭合新行验证: (1) 全新行 None+权威名 → 写真实名非 NULL 且 loader 可见;
    (2) 全新行 None+无权威名 → 写 code 占位非 NULL 且 loader 排除;
    (3) 明确 etf_name=code 占位 → 保持 code 不被真实名替换, loader 排除;
    (4) 已有真实名 + 传入 None 冲突 → 真实名保留。
- 全量 `pytest -q scripts/tests/` 原始末行见实施报告。

## 生产修复建议范围(另案, 不在本代码分支)
- 163109 的 13 行 NULL etf_name: 生产侧用 **DB 现有全称** `申万菱信深证成份指数(LOF)A`
  (DB 3887 行全是全称, 实测一致), 不得用 board_map 短名 `申万深成LOF`(否则 §22 同 code 两名):
  `UPDATE etf_daily SET etf_name='申万菱信深证成份指数(LOF)A'
  WHERE etf_code='163109' AND etf_name IS NULL`(或重跑 pipeline_daily 让契约+采集补真实名)。
- 其余 6 条 NULL 老数据: 按 code 逐一查 **DB 该 code 已有非占位全称**(优先) > board_map 短名
  补 UPDATE(注意全称 vs 短名一致性, 防 §22 同 code 两名)。
- 12 只同类 LOF/163821 待查范围: 核对 fund_type 漂移排除出 LOF 追加采集的 code,
  确认其 etf_daily 行 etf_name 非 NULL(本契约修复后新行不产生 NULL, 但历史残留需补)。
- 7 条历史 freeze 处置另案, 不在本记录伪造。

## 防复发
- 任何新增 fetch_etf_ohlc 消费点: 在 row 上设真实 etf_name 最好; 漏设时 `_upsert_daily`
  前置规范化会解析(DB 名 > 权威名 > code 占位哨兵), 新行不产生 NULL, 冲突不覆盖已有真实名。
- 调用方主动写 etf_name=code 占位哨兵(盘中假数据)会被原样保留, 不被真实名替换(防假数据洗真)。
- 加载器 `etf_name <> etf_code` 过滤是防盘中占位假数据的设计, 不得删除/加 `OR etf_name IS NULL`。
- 生产补数据用 DB 现有全称, 不用 board_map 短名(防 §22 同 code 两名)。
