# etf_daily.etf_name 写入契约缺失根因与防复发(2026-11-07)

## 问题
163109(申万深成LOF) 的 20261021–20261106 共 13 行已补 OHLC+NAV, 但 etf_name 全为 NULL;
真实价格加载函数 `scripts/signal_kelly_backtest.py::_batch_load_etf_prices` 的 SQL 含
`accum_nav IS NOT NULL AND etf_name <> etf_code`, NULL 不满足该条件 → 11-04/05/06 不进入
价格映射, 加载器仍停在 20261020。全表 NULL etf_name 共 19 行(13 条 163109 + 6 条老数据)。

## 根因(文件:行号)
- **直接来源**: 临时脚本 `/tmp/backfill_163109.py`(未提交)调用 `fetch_etf_ohlc()`(
  `app/collector/etf_national_team.py:710`, 返回 dict 只含 date/etf_code/open/close/high/low/amount,
  **不返 etf_name**)后, 按 fields=`["etf_name",...]` upsert, 未在 row 上设 etf_name →
  `_upsert_daily`(`app/collector/etf_national_team.py:1085`) 写入 etf_name=NULL。
- **契约缺陷(根因, 非单脚本)**: `_upsert_daily` ON CONFLICT 裸赋值
  `etf_name=excluded.etf_name`, **无 NULL/空串/code 占位保护** → 任何调用方漏设 etf_name
  即把已有真实名覆盖成 NULL。对比 `scripts/backfill_etf_daily.py:173` 已有
  `COALESCE(NULLIF(etf_daily.etf_name,''),excluded.etf_name)` 保护, 主 `_upsert_daily` 缺这层。
- **同类潜在遗漏**: `scripts/export_etf_score_list.py:384` `etf_name = name_row[0] if name_row else code`
  的 `else code` 兜底把 code 当 name 写入(占位行被加载器 `etf_name<>etf_code` 过滤);
  `_board_etf_map_lof_codes`(`app/collector/etf_national_team.py:301`)
  `name = ... or code` 写库占位。

## 写入路径审计清单(fields 含 etf_name 的 _upsert_daily 调用)
| 文件:行号 | 路径 | 是否设真实名 | 本次 NULL 关联 |
|---|---|---|---|
| etf_national_team.py:1312 | pipeline_daily | 是(L1311 r["etf_name"]=universe name) | 否(生产正常) |
| etf_national_team.py:1406/1435 | pipeline_intraday_close | 是(L1405/1433 ETF_LIST name) | 否 |
| etf_national_team.py:1656 | pipeline_intraday_realtime | 是(ETF_BY_CODE name) | 否 |
| etf_national_team.py:1735 | pipeline_backfill | 是(worker L115 r["etf_name"]=name) | 否 |
| etf_national_team.py:2466 | update_accum_nav | fields=["accum_nav"] 不含 etf_name | 安全 |
| export_etf_score_list.py:274 | _fetch_and_upsert_ohlc | 是(caller 传 name) | 取决于 name 来源 |
| export_etf_score_list.py:387 | _compute_volatility 补采 | **else code 兜底(已修)** | 同类潜在 |
| 临时脚本 backfill_163109.py | fetch_etf_ohlc 直调 | **否 → NULL(本次直接来源)** | **是** |

fetch_etf_ohlc 消费点(etf_national_team.py:90/110/1387, fetchers.py:278, multisource.py:396,
export_etf_score_list.py:269/376)均不返 etf_name, 名称由调用方注入。

## 契约规则(唯一解析顺序)
1. 调用方明确传入的真实名称(非 NULL/非空串/非与 etf_code 同值占位) → 用它
2. DB 中该 code 已有的非空且非 code 占位名称 → 保留
3. 权威基金元数据 board_etf_map.json 中该 code 的 name → 用它
4. 无权威名称时禁止写 NULL(保留已有好名称; 确无名称则维持显式占位语义, 不得产生 NULL)

## 修复(本分支 feat/signal-gap-name-contract-20261107)
1. **`_upsert_daily` SQL 单点保护**(`app/collector/etf_national_team.py:1085`):
   ON CONFLICT 时 etf_name 改 CASE 表达式 — 调用方传真实名 > DB 已有真实名 > 保留 DB 原值,
   不把已有真实名清成 NULL/空串/code 占位。所有 caller 自动受益(根因单点修复)。
2. **新增 `_resolve_etf_name_authoritative(code)`**(`app/collector/etf_national_team.py`):
   从 board_etf_map.json 解析权威名, 无则返 None。
3. **`export_etf_score_list.py:384` else code 收紧**: 改为 DB 已有名 > board_etf_map 权威名;
   都无时不写 etf_name(从 fields 移除), 交给 _upsert_daily ON CONFLICT 保护, 不产生 NULL/占位。
4. **`_board_etf_map_lof_codes` L301 `or code` 收紧**: board_etf_map 无 name 时返 None(写库不占位)。

## 测试证据
- 新测试 `scripts/tests/test_signal_gap_name_contract_20261107.py`(8 passed):
  - 直接调用 `_batch_load_etf_prices`(monkeypatch 临时 DB, 不复制 SQL):
    A 真实名行进映射 / B etf_name=code 占位仍被排除 / C NULL 行仍被排除 / D 混合只真实名进映射
  - 直接调用 `_upsert_daily`: NULL/空串/code 占位不覆盖已有真实名 / 真实名覆盖占位
- 全量 `pytest -q scripts/tests/` 原始末行见实施报告。

## 生产修复建议范围(另案, 不在本代码分支)
- 163109 的 13 行 NULL etf_name: 生产侧 `UPDATE etf_daily SET etf_name='申万深成LOF'
  WHERE etf_code='163109' AND etf_name IS NULL`(或重跑 pipeline_daily 让契约保护+采集补真实名)。
- 其余 6 条 NULL 老数据: 按 code 逐一查 board_etf_map.json 权威名补 UPDATE。
- 12 只同类 LOF/163821 待查范围: 核对 fund_type 漂移排除出 LOF 追加采集的 code,
  确认其 etf_daily 行 etf_name 非 NULL(本契约修复后新行不会写 NULL, 但历史残留需补)。
- 7 条历史 freeze 处置另案, 不在本记录伪造。

## 防复发
- 任何新增 fetch_etf_ohlc 消费点: 必须在 row 上设真实 etf_name(非 code 占位), 否则
  _upsert_daily ON CONFLICT 保护会保留 DB 已有名(新行 INSERT 仍写 NULL, 需调用方保证)。
- 加载器 `etf_name <> etf_code` 过滤是防盘中占位假数据的设计, 不得删除/加 `OR etf_name IS NULL`。
