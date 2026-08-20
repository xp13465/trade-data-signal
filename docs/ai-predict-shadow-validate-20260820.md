# 影子模式验证：方向锚/反思归因 7 天 A/B（2026-08-20 用户拍板）

> 触发：AI 预测自成长轮次 3（方向锚语义教学 + 反思=因子归因回灌）已合入 main（commit `30ed2c94c`，全默认关，线上 prompt 逐字不变）。用户拍板 2026-08-20："影子模式跑 7 个真实交易日，用数据决定开/不开/改"。测试基准 = current baseline（memory `test-baseline-v112-anchor`，本验证**不改任何线上默认输出**，不算动核心默认，故不发版本）。

## 一句话定义
**影子模式 = 线上输出完全不变，但后台把「方向锚/归因会预测什么方向」算出来、按 date 落盘；次日真实盘后回填实际方向，聚算 7 天命中率。** 它不改线上预测，只在旁路记录影子预测，供 7 天后数据决策。不碰 write_outputs 主链 / 不发邮件 / 不上传 / 不通知。

## 为什么做（背景）
- 方向锚（`_compute_direction_anchor`，L205）+ 语义教学（`_direction_anchor_semantics`，L303）+ 反思归因（`_attribut_factor`，L2678 / `build_attribut_inject`，L2936）已合入，**全部默认关**（`direction_anchor_enabled` / `reflection_factor_attribution_enabled` 均 false）。
- 现状摸清：
  - 方向锚默认关时 `_compute_direction_anchor` **连算都不算**（L1258/L1753 的 `if cfg.get("direction_anchor_enabled")` 拦在计算前）。
  - 反思归因的因子级影子数据（失败样本 `factor_attribution`）**已随 `_classify_failure` 落盘**（L2838 不受反思开关拦）。
- 所以影子模式核心缺口 = ①方向锚默认关时不算（需补"关着也后台算一次+落盘影子预测，不注入"）②方向锚无影子预测逐日落盘+命中率聚算 ③反思归因有数据但无聚算脚本。

## 影子语义与实列同源（关键证据）
影子 lean 合成（`gen_daily_brief._shadow_lean`，L390）**读取与 `_direction_anchor_semantics` / `_attribut_factor` 完全同一批因子字段**（turns = to_long/to_short、ma_bull、nq_open_low/nq_chg、rate_down_channel、us10y、gold），绝不另造一套口径：
- 任一强转多（T1）→ lean `up`（顺势看涨 64-66%）。
- 任一强转空（T2/T3）→ lean **up（非 down!）**（逆势看涨，同语义 8/14·8/17 验证：转空次日不跌、全时段净流出≠偏空）。
- L3 纳指大跌（nq_chg ≤ -0.8%）→ **压过**看多信号，lean 打回 `flat`（压制≠转空证据，不硬猜 down），与语义"L3 可压过 T1 转多看涨"同构。
- 无 T 转向但均线多头（ma_bull）→ soft `up`；均无 → `flat`。
- 与 `_attribut_factor` 归因判定（L2696-2720：L3压制看多 / 转空被当偏空 / T1+均线多头强规则）逐条对齐，保证影子 miss 的归因与实列归因指向同一批因子。

**缓存去重（不算双份）**：`_compute_direction_anchor` 加模块级 FIFO 缓存（L205 `_DIRECTION_ANCHOR_CACHE`，上限 16 键，键=(db,date) 同结果确定性唯一）。影子旁路与实列注入同 (db,date) 时**只读一次 DB**，二者取同一 `out` 的副本，不双份计算、不污染。

## 怎么跑（工程实现）
### 落盘（每次 gen_daily_brief.py 主流程自动）
- `config/daily_brief.yaml` 加 `shadow_mode_enabled: true`（默认开=好收集数据）。⚠️ 它**只控制旁路落盘，不注入线上**——即使 true，`direction_anchor_enabled`/`reflection_anchor_enabled` 全关时 prompt 仍逐字不变。
- `main()` 在 `load_data` 后新增旁路调用 `record_shadow(date, cfg, db_path, repo)`（L3496 区）：无论方向锚开关开否，都调一次 `_compute_direction_anchor` 合成 `pred_shadow`，按 date **追加**（同 date 幂等覆盖，老日期保留）落盘 `data/brief_shadow.json`。
- 影子写在 AI 生成之前：即使 AI 降级 rule/minimal，影子照样记录（影子价值=独立于线上预测的备选信号，需 7 天逐日样本）。

### 对账+聚算（次日盘后手动/定时跑）
```bash
python scripts/aggregate_shadow.py            # 回填全部可回填 actual + 聚算
python scripts/aggregate_shadow.py --date 20260820   # 单日对账
python scripts/aggregate_shadow.py --json     # JSON 输出
```
- `aggregate_shadow.py` 先**回填**：对每个影子记录，找其后第一个真实交易日 sh 涨跌幅（index_daily），按 `HIT_THRESHOLD=0.5`（与 `gen_daily_brief._actual_direction` 同口径）判 `actual_direction`，回写 `brief_shadow.json` 的 `actual` 字段（幂等，已回填跳过）。DB 不可用/无下一交易日 = 留空不硬判。
- 再**聚算**：影子命中率 = `pred_shadow(up/down/flat) == actual_direction` 比例；按 pred_shadow 分桶；按 basis 因子分组统计 miss 伴随频次（top 误导向量）；flat 单列（无方向空转不计加权）。

## 7 天验证协议（2026-08-20 起）
| 日 | 动作 |
|---|---|
| 每个真实交易日 | launchd 20:40 跑 `gen_daily_brief.py` 顺带自动记录影子（无需人工） |
| 每交易日次日盘后 | `python scripts/aggregate_shadow.py` 对账上一日（回填实际方向 + 聚算累计命中率） |
| 第 7 个真实交易日盘后 | 满 7 样本，跑最终聚算，把「全样本命中率 + 非flat命中率 + top误导向量 + 按lean分桶」汇报主控，用户据数据拍板开/不开/改 |

判定基准（预期校准，不预设拍板）：
- 影子方向锚整体命中率 ≥ 基线（AI 预测方向命中率，memory `test-baseline-v112-anchor`）→ 支持"开注入验证实操增益"。
- 非 flat 样本命中率显著（≥60% 且样本 ≥5）→ 支持方向锚确有方向信号。
- top 误导向量（如 L3 纳指大跌反复miss）→ 支持"改"（调加权/阈值）而非直接开。

## 复现
- **脚本**：`scripts/gen_daily_brief.py`（影子落盘，活脚本）+ `scripts/aggregate_shadow.py`（聚算，本验证新建）。
- **输入依赖**：`config/daily_brief.yaml`（`shadow_mode_enabled`）+ `data/brief_shadow.json`（影子记录）+ `trade-data/data/sentiment.db`（futures_position/daily_metric/index_daily，影子因子与次日 sh 涨跌均从它读）。
- **重跑命令**：
  - 生成 + 影子落盘：`python scripts/gen_daily_brief.py --no-upload --no-tts --mock`（mock 代表 AI 主链，影子在主链前置旁路，无论如何都会算）。
  - 对账 + 聚算：`python scripts/aggregate_shadow.py [--date YYYYMMDD]`。
- **数据截止**：影子因子=对应预测日 DB 值；聚算=index_daily 最新交易日。
- **关键口径一句话**：影子 lean 由方向锚 T（转多→up；转空逆势→up）+ L（纳指大跌压过看多→flat；无T+均线多头→up）合成，与 `_direction_anchor_semantics` 同源；命中 = 次交易日 sh 涨跌幅方向（>0.5% up / <-0.5% down / 否则 flat）与影子 lean 相等。
