# 基笔唯一化三表 Schema(L42 数据瘦身步1 实施落档)

日期:2026-09-20 | 角色:implementer | 状态:已实现于 feat/kelly-unique-export(signal_kelly_backtest.py, 环境变量 KELLY_UNIQUE_EXPORT 开关)
测试基准:current baseline v1.1.7(口径权威见 memory test-baseline-v112-anchor);本步只做数据形态(唯一化存储),不重算口径,生成字段值以原 trades_output 为准逐位对账。

## 一、字段划分实证(本地 9-13 05:10 主档,rating_high 全量 86 基笔跨 A~J 逐字段对比)

### 1.1 19 个共享字段(跨 mode 100% 全同,实测 86/86 零差异)

| # | 字段 | 原 TRADE_FIELDS 索引 |
|---|---|---|
| 0 | signal_date | 0 |
| 1 | index_id | 1 |
| 2 | signal | 2 |
| 3 | buy_date | 3 |
| 4 | etf_code | 5 |
| 5 | etf_name | 6 |
| 6 | track_tier | 7 |
| 7 | track_score | 8 |
| 8 | match_method | 9 |
| 9 | track_low_confidence | 10 |
| 10 | buy_price | 11 |
| 11 | shares | 13 |
| 12 | real_buy_price | 19 |
| 13 | real_buy_date | 20 |
| 14 | market_state | 22 |
| 15 | market_tier | 23 |
| 16 | market_tier_all | 24 |
| 17 | market_tier_cyb | 25 |
| 18 | rating | 26 |

### 1.2 8 个卖出侧字段(随 mode 变)

| # | 字段 | 原 TRADE_FIELDS 索引 | 变化实态 |
|---|---|---|---|
| 0 | sell_date | 4 | 86/86 全随 mode 变 |
| 1 | sell_price | 12 | 86/86 全随 mode 变 |
| 2 | profit | 14 | 86/86 全随 mode 变 |
| 3 | return_pct | 15 | 86/86 全随 mode 变 |
| 4 | hold_days | 16 | 86/86 全随 mode 变 |
| 5 | sell_reason | 17 | 86/86 全随 mode 变 |
| 6 | current_price | 18 | 33/86 随 mode 变,53/86 全同 |
| 7 | real_current_price | 21 | 33/86 随 mode 变,53/86 全同 |

### 1.3 current_price / real_current_price 变化机制实证(方案标注「部分随 mode 变」的定性)

- 变化的 33 基笔全部是「部分 mode 已卖、部分 mode 未卖」的持仓笔:A/B/C/D/E/F/J 固定规则到期即卖 → current_price 为空字符串;G/H/I 信号驱动可能持有到回测结束未触发卖出 → current_price=最新净值(非空)。同一基笔在已卖 mode 与未卖 mode 的 current_price 取值不同 → 逐字段对比显示「随 mode 变」。
- 全部已卖(53 基笔)的 current_price/real_current_price 跨 mode 全同。
- 结论:**8 个卖出侧字段全部必须放变体表**,不能把 current_price/real_current_price 归共享(部分基笔跨 mode 不一致,归共享即丢值)。这印证方案 §二 标注。

### 1.4 跨 qk 一致性实证(主表从任意 qk 取共享字段都行)

- 全数据 7,608 基笔 × 恰好 4 个 qk(rating/etf/sig/mkt 各一,前缀组合 100% 为 {etf,mkt,rating,sig}),零例外。
- 跨 qk 同 (base_key, mode) 的 **27 列全字段** 30,432×10 对比零差异(含卖出侧)。
- 每基笔 10 mode 全覆盖(7,608 键 × 10 = 76,080 (key,mode) 条,全同)。
- 结论:主表共享字段从该基笔任一出现 qk 的任一行取都行;变体表从任一 qk 取都行;归属=基笔出现的 4 个 qk 枚举。

## 二、三表 Schema(产物文件)

- 主档:`static-site/data/signal_kelly_trades_unique.json`(主档 KELLY_BUY_NEXTDAY=1 口径)
- sdc 档:`static-site/data/signal_kelly_trades_sdc_unique.json`(KELLY_BUY_NEXTDAY=0 口径,双套各自独立生成,基笔数不等不共用,见消费方审计 §1.5)
- 单文件内含逻辑三表(base 主表 + variants 变体表 + qk_groups 归属枚举)

```json
{
  "generated_at": "2026-09-20 21:00",
  "buy_amount": 10000,
  "period_cutoffs": { "y1": "20250920", "y3": "...", "all": "0" },
  "modes": ["A","B","C","D","E","F","J","G","H","I"],
  "fields": ["signal_date","index_id","signal","buy_date","etf_code","etf_name","track_tier",
             "track_score","match_method","track_low_confidence","buy_price","shares",
             "real_buy_price","real_buy_date","market_state","market_tier","market_tier_all",
             "market_tier_cyb","rating"],
  "variant_fields": ["sell_date","sell_price","profit","return_pct","hold_days","sell_reason",
                     "current_price","real_current_price"],
  "base_key_fields": ["signal_date","index_id","signal","buy_date","etf_code"],
  "qk_groups": {
    "rating": ["rating_high","rating_mid","rating_low"],
    "etf":    ["etf_strong","etf_related","etf_approx","etf_has_track"],
    "sig":    ["sig_main","sig_aux","sig_special","sig_backup"],
    "mkt":    ["mkt_a","mkt_hk","mkt_global","mkt_industry","mkt_concept"]
  },
  "n_base": 7608,
  "base": [
    [ /* 19 共享字段值 */, 3, 1, 0, 4 ],   // 尾部 4 个 = 各 qk_group 枚举码(对应 qk_groups 顺序)
    ...
  ],
  "variants": {
    "A": [ [ /* 8 卖出字段值 */ ], ... ],  // 长度 = n_base,索引 i ↔ base[i]
    ...
  }
}
```

- 归属尾列:每基笔 4 个枚举码,顺序 = qk_groups 键序(rating/etf/sig/mkt);某组无归属时 = -1(当前数据零 -1,兜底兼容)。
- 每基笔行序:base 按 base_key 首元素 signal_date 升序(同日按 base_key 全键排序),variants[mode] 与 base 同索引对齐。

## 三、无损还原规则

还原为原 `quadrants[qk][mode]` 行(27 列,原 TRADE_FIELDS 列序):

1. 遍历 `base` 每行 i:共享 19 值 + 归属 4 枚举码。
2. 遍历 `variants` 每 mode:取 variants[mode][i] 的 8 卖出值。
3. 拼 27 列:按 TRADE_FIELDS 原列序,字段 ∈ fields(共享)从 base 取,字段 ∈ variant_fields 从变体取。
4. 归属:枚举码 → qk_groups[组][码],该基笔进这些 qk 的该 mode;码 = -1 的组跳过。
5. 输出行值必须与原 trades_output `quadrants[qk][mode]` 该 (qk,mode,base_key) 行**逐位一致**(对账基准)。

对账方法(§5.4⑦ 同构对账铁律):
- 集合等价:三表重建的 {(qk, mode, base_key)} 键集 == 原 quadrants 键集,零缺零多。
- 值逐位:遍历原 quadrants 每行,base_key 索引三表还原 27 列,与原行逐位比对;304,320 行(4qk×10mode×7608)全 PASS。

## 四、体积实测(本地 9-13 主档 78,296,778 字节)

| 形态 | 原始字节 | gz 字节 |
|---|---|---|
| 原 signal_kelly_trades.json | 78,296,778 (74.7 MB) | 12,784,087 |
| 三表 unique | 5,246,852 (5.0 MB) | 1,287,225 |
| 压缩率 | **14.9x** | **60.8x** |

- 比方案预估(15 MB)更好:多数卖出字段为短值/空值,json.dumps 紧凑序列化后实际 5.0 MB。
- 兜底语义(§24 教训):原 75MB 全量兜底将由 unique 全量 ~5MB 替代,「分片失败回退全量」保留。

## 五、生成端实现要点

- 开关:环境变量 `KELLY_UNIQUE_EXPORT`(默认 0 关闭);关=完全不生成三表,现有产物零变化。
- 独立函数 `_build_unique_tables(quadrants)` 由 `_classify_buy_rows` 的 quadrants 中间态直接生成,不触碰 `_build_outputs`(output/trades_output)任何逻辑。
- compute_intraday 共用 `_build_outputs`(L1844)不受影响——三表导出只在 compute 主流程 main() 末尾显式调用,盘中档不触发(盘中档无 40 倍膨胀,唯一化无必要,见消费方审计 §2.2)。
- 双套独立:main() 在 KELLY_BUY_NEXTDAY=1/0 两次运行时各自生成自己的 unique 文件,文件名带 _sdc 后缀区分,不共用(主档基笔集 ⊂ sdc,基笔数不等)。
- 产物只写 static-site/data/(正常上线渠道),不提交 git(由运行回测生成)。
