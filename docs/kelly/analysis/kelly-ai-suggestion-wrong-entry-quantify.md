# 量化「错进 AI 建议」:修复前历史次数 + 修复后干净验证(2026-08-14)

> 生成:2026-08-14。只读分析,不改代码。
> 关联上线 commit:`8e6e14cad`(#25,fix(首页AI建议): 入样宇宙1:1对齐凯利回测)。
> 复用脚本:`scripts/replay_candidate.py`(回放修复前候选构建+目标类别错进统计)、`scripts/full_sweep.py`(signal_daily 全类别清扫)。
> 数据源:sentiment.db `signal_daily`、board_etf_map.json、config/indicators.yaml。

---

## 0. 摘要

**背景**:#25(2026-08-14 上线,_bt_in_universe 入样宇宙过滤)后,量化「空数组/无 key/港行行业标的」修复前错进首页 AI 建议候选的历史次数,并验证修复后干净。

**一句话结论**:**修复前 814 债类 bug 错进候选 882 次 / 748 交易日确凿;空数组/无 key 标的在默认档位筛选下错进=0,仅"清空筛选/全档位"时错进(修复前 10252 条/3130 交易日 + 6895 条/3668 交易日);修复后目标类别错进=0,今日 overview 172 条 signals_today mismatch=0,true 83 条全是有 key 有 track_score,无漏网类别。**

诚实标注:候选层错进 882 次确凿;**是否真进 top1 取决于当日排序**(默认 K=1 时 cgb track_score=None 垫底通常被挤出,K 增大或候选少才可能进 top1)。

---

## 1. 修复前候选判定(机制)

修复前首页 AI 建议候选判定(**无 _bt_in_universe 过滤**):

1. `index_id` 非 `s.*`(overview() 已排除情绪分)
2. `signal != "band_hold"`(修复前 _dayItems 显式排除)
3. 默认 ETF 档位筛选 `sigEtfFilterSet=["1","2","3","4"]`(app.js `state` 初始值,见 app.js L11/L2006-2011):
   - `_signalTiers(it)`:etfs 空 → 5;否则 `min(_etfTier)`
   - `_etfTier`:`match_method="self"` → 1;`track_tier` strong=1/related=2/approx=3/none|null=4;undefined 回退 grade

**不排除 sell / sell_stop_loss**(修复前这些卖类信号同样可进候选)。

## 2. 814 债类 bug 真正机制(self ETF 挡不住默认筛选)

- **根因**:`cgb_10y_etf` 是 self ETF(`match_method:"self"`,queries.py `_self_etf_for` L297-320)→ `_etfTier=1` → 默认档位筛选(1-4)即保留 → 修复前候选错进。
- **修复前错进量**:882 条 / 748 交易日。
  - signal 分布:`sell` 419 / `buy_special` 236 / `buy_aux` 146 / `sell_stop_loss` 47 / `buy` 18 / `buy_backup` 16。
- **修复后**:今日 overview 其 self ETF `track_score=[None]` → `_bt_in_universe=false` → 正确排除。

## 3. 空数组 / 无 key 标的:默认筛选错进=0,全档位才错进

- **空数组**(ftse100/kospi 等 31 个)与**无 key 标的**(cgb_idx/cgb_10y_future/hk_* 8 个)是档 5 → **默认档位(1-4)下修复前错进=0**。
- 只在"清空筛选/全档位"时错进:
  - 空数组:修复前 10252 条 / 3130 交易日
  - 无 key:6895 条 / 3668 交易日

## 4. 顺带:有 key 无 track

- 有 key 无 track(csi_000813 等)129 条 / 129 交易日,修复前也错进(档位判定命中但 track_score 为空)。

## 5. 修复后干净验证(今日 2026-08-14 overview.json)

- 172 条 signals_today `mismatch=0`;`_bt_in_universe=true` 83 条,**全是有 key 有 track_score**。
- `us_ndx/us_dji/us_spx/us_ixic/nikkei225/dax/cac40/hsi/hscei` 全部仍入样(正常保留)。
- 空数组 31 key / 有 key 无 track 均正确排除。
- 默认档位筛选 + `_bt_in_universe` 双保险;无漏网类别。

## 6. 诚实标注:候选 vs top1

- **候选层**错进 882 次确凿。
- 是否真进 top1 取决于当日排序:默认 K=1 时 cgb track_score=None 垫底通常被挤出;K 增大或候选少时 cgb_10y_etf 才可能进 top1(复现脚本近 15 交易日窗口与 K=1 口径分析见 `scripts/replay_candidate.py` 尾部)。

---

## 7. 证据

| 证据 | 位置 |
|---|---|
| 修复前档位筛选/候选判定 | app.js L11(默认 sigEtfFilterSet) / L1632-1662 / L2006-2011 / L2090-2092 |
| self ETF 注入 + _bt_in_universe | queries.py `_self_etf_for` L297-320 / `_bt_in_universe` L799 |
| self ETF func/symbol 配置 | config/indicators.yaml L316-324 |
| board_etf_map(149 keys,31 空数组) | data/board_etf_map.json |
| signal_daily 全历史(70296 行/6824 交易日/178 index_id) | data/sentiment.db,app/db.py L47 |
| 今日 overview | overview.json(8/14 16:32) |
| #25 上线 commit | `8e6e14cad` |

---

## 8. 引用脚本

| 脚本 | 作用 |
|---|---|
| `scripts/replay_candidate.py` | 回放「#25修复前」候选构建,统计目标类别错进历史次数(默认筛选/全档位/近15日/K=1 top1) |
| `scripts/full_sweep.py` | signal_daily 全类别清扫:按 board_etf_map/self 分类,回放修复前/后候选错进 |

> 两脚本从 /tmp 归档至此(2026-08-14),头部已补注释块(日期/结论/依赖/复现命令)。依赖:sentiment.db + board_etf_map.json + config/indicators.yaml;复现:`python3 replay_candidate.py` / `python3 full_sweep.py`(cwd 需能访问 ROOT 数据路径)。
