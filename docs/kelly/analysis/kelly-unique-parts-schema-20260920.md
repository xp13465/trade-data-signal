# 分片唯一化三表 Schema(L42 数据瘦身步2 Phase1 实施落档)

日期:2026-09-20 | 角色:implementer | 状态:已实现于 feat/kelly-unique-parts(signal_kelly_backtest.py `_export_unique_parts`,环境变量 `KELLY_UNIQUE_EXPORT` 开关,默认关)
测试基准:current baseline v1.1.7(权威见 memory test-baseline-v112-anchor);本步只做数据形态(分片也走唯一化存储),数值口径零改动,生成字段值以原分片 quadrants 为准逐位对账。

## 〇、关系定位

- 步1(全量唯一化三表)落档:`docs/kelly/analysis/kelly-unique-schema-20260920.md`(全量 `signal_kelly_trades_unique.json`,76.6MB→5.6MB)。
- 本步 = 步2(前端直接吃三表)的**生成端前置**:前端要读「唯一化分片」,先把分片也切成三表结构。
- 分片三表对步1 全量三表**完全同构**(同一个 `_build_unique_tables` 产出):字段划分 19 共享/8 卖出、基笔键、qk 归属枚举全部复用步1 结论,**不重新发明**(一致性铁律)。

## 一、产物与命名

分片唯一化三表落在**既有分片同一目录** `signal_kelly_trades_parts/`(sdc 为 `signal_kelly_trades_sdc_parts/`,由 trades_path 文件名派生,双套各自独立生成,基笔数不等不共用):

| 产物 | 内容 | 与旧分片关系 |
|---|---|---|
| `unique_recent.json` | signal_date ≥ recent_cut 的基笔三表 | 与 `recent.json` **同窗** |
| `unique_t{YYYY}.json` | signal_date 年份 = YYYY 的基笔三表 | 与 `t{YYYY}.json` **同界** |

旧 quadrants 分片(`recent.json`/`t{YYYY}.json`)照旧生成,**不受影响**;开关关=本函数完全不触发,现有产物 diff 零变化。

## 二、单文件结构

每片文件与全量三表结构逐字段对齐(前端解析逻辑可复用):

```json
{
  "generated_at": "2026-09-20 21:00",
  "buy_amount": 10000,
  "period_cutoffs": { "y1": "...", "y3": "...", "all": "0" },
  "modes": ["A","B","C","D","E","F","J","G","H","I"],
  "fields": [ /* 19 共享字段, 与全量一致 */ ],
  "variant_fields": [ /* 8 卖出侧字段 */ ],
  "base_key_fields": ["signal_date","index_id","signal","buy_date","etf_code"],
  "qk_groups": { "rating": [...], "etf": [...], "sig": [...], "mkt": [...] },
  "n_base": 269,        // 本片基笔数
  "base": [ [/* 19 共享 */, 3, 1, 0, 4], ... ],        // 尾部 4 = qk_group 归属枚举码, -1=无归属
  "variants": { "A": [ [/* 8 卖出 */], ... ], ... }   // 每 mode 数组, 长度 = n_base, 索引 i ↔ base[i]
}
```

- **切法 = 按基笔 signal_date 年切主表,变体行跟着基笔走**:归属年份=基笔 signal_date 年份,与卖出日期无关(跨年基笔:signal 2029 卖出 2020 → 只进 `unique_t2019`,卖出字段跨年保真)。
- recent 边界 `recent_cut` 由 `_export_trades_parts` 的自适应窗口探针(120/90/60 天,序列化 ≤3MB)决定,**与 quadrants `recent.json` 同窗复用**,不另算。
- 与年片重叠:热区内的基笔同时存在于 `unique_recent` 与当年 `unique_t{YYYY}`,前端两策略互斥取用(热区内只用 recent/超出只用年片),拼接不重复计数——与旧分片语义一致。
- 空年份不出文件(与 quadrants 分片同策略)。

## 三、无损还原规则

对每片(把 `unique_{name}` 还原为 `{name}` 的 quadrants):

1. 遍历 `base` 每行 i:19 共享值 + 4 归属枚举码。
2. 遍历 `variants` 每 mode:取 `variants[mode][i]` 8 卖出值(None 哨兵=该基笔该 mode 无有效回测,跳过)。
3. 按 `TRADE_FIELDS` 原列序拼 27 列,该基笔进归属 qk 的该 mode。
4. 输出行值必须与原分片 `{name}` 的 `quadrants[qk][mode]` 该 (qk, mode, base_key) 行**逐位一致**(对账基准)。

对账方法(§5.4⑦ 同构对账铁律):`scripts/check_kelly_unique_parts_restore.py --trades <trades.json>`
- 对每个分片(recent + 全部 t{YYYY})做 A 键集等价 + B 值逐位 + C 总行数 三查;任意一片 FAIL 退出码 1。
- 重建逻辑复用 `scripts/check_kelly_unique_restore.py:build_rebuilt`(单一实现,防漂移)。

## 四、体积实测(本地 9-13 展示档)

| 档 | 原分片 quadrants(recent+t*) | 唯一化分片 | 压缩率 |
|---|---|---|---|
| 主档 | 79,122.7 KB | 5,966.8 KB | **13.3x** |
| sdc | 79,195.1 KB | 5,971.8 KB | **13.3x** |

- gz 未计(分片与旧分片一样不生成 .gz,CF 自动 br)。
- 体积随基笔交易日增长浮动(与全量三表同因)。

## 五、生成端实现要点

- 开关:`KELLY_UNIQUE_EXPORT`(默认 0 关闭);关=完全不生成,现有产物零变化。
- 实现:`_export_trades_parts` 内捕获 recent 边界(`recent_rows`/`recent_cut`)与年份 id 集 `by_year`,末尾 `if KELLY_UNIQUE_EXPORT:` 调 `_export_unique_parts(parts_dir, recent_rows, recent_cut, by_year, grouped)`。
- `_export_unique_parts` 对每片 quadrants 直接调 `_build_unique_tables`(步1 同函数),序列化参数与全量一致(`ensure_ascii=False, separators=(",", ":")`),原子写 `_atomic_write`。
- 双套独立:主档/sdc 各自跑 main() 时由 trades_path 派生 parts 目录,各自生成自己的 unique 分片。
- compute_intraday(盘中档)不触发分片导出,故也不触发分片唯一化。

## 六、边界语义(自测覆盖)

- 空年份片:无行的年份不出 `t{YYYY}`/`unique_t{YYYY}`。
- recent 热区窗:unique_recent 与 quadrants recent 同窗、逐位一致。
- 跨年基笔:基笔 signal_date=2019、卖出于 2020 → 只归 `unique_t2019`,卖出字段跨年保真。
- 开关零变化:KELLY_UNIQUE_EXPORT=0 vs =1 时,quadrants 分片文件逐字节一致;真实数据重新生成的分片与线上生产分片(recent+t* 共 17 个文件×双套)逐字节一致。
