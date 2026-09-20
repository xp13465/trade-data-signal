# 指数收盘价定稿校验设计(2026-09-18)

> 调研产出(researcher):从源头减少「未定稿假收盘价 → 信号漏算/迟到补出」。
> 事故背景:9-17 晚 gz_399396 落库未定稿假收盘价 14039.06(实为当日某时点价),次日修正为
> 真值 14096.55 后布林条件翻转,全历史重算补出 9-17 迟到信号 → 冻结表缺键告警。

---

## 0. 事故链路(证据钉死)

写库途径已排除盘中反哺(INDEX_CODES 无 sz399396),锁定 = **新浪主源 runner.step2**:

1. **17:50 update_all**(云上 `trade-update-all.timer`,systemd 实测)→ runner.step2 用
   `ak.stock_zh_index_daily`(新浪)采集全部 enabled 指数拉近 400 天
   - `app/collector/fetchers.py:766 collect_index` → `app/collector/runner.py:138 upsert_index_rows`
   - **upsert_index_rows 纯 UPSERT,无任何定稿校验**(runner.py:138-153)
2. **新浪源对部分指数盘后返回「OHLC 全等未定稿 bar」**:
   - 云上 `index_daily` 实测 9-18 有 **15 个指数**全等行(open=high=low=close,amount=None):
     csi_000102/csi_000330/csi_000673/csi_970070/gz_399365/gz_399368/gz_399395/gz_399396/
     gz_399417/gz_399431/gz_399439/gz_399440/hk_hscci/hk_hsmpi/sz_div
   - 本地库保留 9-17 同样 15 个全等行(gz_399396=14039.06 与事故描述逐位吻合)
   - **新浪源定稿时点晚于 17:50**:9-18 当前(21:00)新浪已定稿 close=14158.916(本地实测),
     但云上 9-18 行仍 14091.23 未覆盖(当晚无重跑机制)
3. **20:35 intraday_snapshot 流程 `_recompute_signals`**(intraday_snapshot.py:2044-2057)调
   `signals.compute()`(app/compute/signals.py:942)读 index_daily 假 close → 算假/漏 signal_daily
4. **20:39 check_signals**(update_all.sh:137)发信号邮件
5. **次日定稿覆盖 → 全历史重算 → 补出迟到信号 → signal_kelly_backtest 冻结缺键告警**
   (`scripts/signal_kelly_backtest.py:245 _alert_frozen_missing`)

现状唯一防线 `index_backfill.py:240 verify_and_backfill_indices` 只校验 close 非空,且只覆盖
10 个 CORE_A_INDICES + 31 个 SW,概念指数(gz_*/csi_*/部分 hk/sz_div)完全无防线。

---

## 1. 业界「收盘定稿校验」调研

### 1.1 A股收盘定稿规则(佐证)
- 沪深两市**收盘集合竞价 14:57-15:00**,不可撤单,以最大成交量原则撮合确定收盘价,
  **15:00 收盘后收盘价才定稿**。盘中/收盘前拿到的当日 bar 收盘价为未定稿。
- 佐证:百度文库/头条「A股收盘集合竞价规则详解(沪深两市)」(14:57-15:00、不可撤单、价格确定原则)。

### 1.2 数据源发布时点不统一(佐证)
- AKShare 官方文档(akshare.akfamily.xyz/introduction.html):「获取的是各财经数据网站公布的**原始数据**」,
  不保证定稿状态,建议多源交叉验证。
- 本仓既有认知(index_backfill.py 头注释):新浪收盘后**偶发延迟发布当日数据**(2026-07-24 曾当日未出);
  baostock T+1;申万行业 T+1(周五数据周一才更新);腾讯补采无 amount。
- **本地实测铁证**(高于社区推断):新浪 `stock_zh_index_daily('sz399396')` 当前(9-18 21:00)返回
  9-18 定稿行 `open=14091.233 high=14182.591 low=14081.455 close=14158.916`,而云上库 9-18 行
  仍为全等假 bar 14091.23 → 证明新浪当晚返回过全等未定稿 bar,且无机制二次覆盖。

### 1.3 未定稿 bar 可判断特征(可落地清单)
| 特征 | 判断式 | 误伤风险 | 数据源支持 |
|---|---|---|---|
| **OHLC 全等(唯一价格点)** | `open==high and high==low and low==close` | **指数历史实测 0 误伤**(见 §4) | 新浪/东财/腾讯当日未定稿均可能 |
| close==open 且 high==low | 同类,等价于 OHLC 全等 | 同上 | 同上 |
| 与实时行情价交叉验证 | 当日 close 明显偏离任一实时源最新价 | 需处理源间复权差异 | 腾讯实时(INDEX_CODES 内) |
| 第二源定稿确认 | 双源当日 OHLC 一致后才视为定稿 | 低(双源一致基本定稿) | 东财 push2his / 腾讯 / baostock(T+1) |

**注意不要用**:amount/成交量(新浪源本身无 amount 字段,正常行也全 NULL——本仓数据实测 9-10~9-16
amount 全 NULL);pct 与昨收自洽性(假 bar 的 close 也是真实某时点价,pct 天然自洽,无法区分)。

---

## 2. 接入点清单(文件:行号)

### 2.1 写 index_daily 的入口(全部 UPSERT,无校验)
| 位置 | 说明 |
|---|---|
| `app/collector/runner.py:138` `upsert_index_rows` | **主嫌疑:17:50 新浪主源采集落库**(事故写入点) |
| `app/collector/intraday_snapshot.py:1124` `_backfill_index_daily` | 盘中反哺 16 INDEX_CODES(不含 gz_*,但统一防线) |
| `app/collector/intraday_snapshot.py:1177` `_backfill_industry_daily` | sw_ 行业反哺 |
| `app/collector/intraday_snapshot.py:1315` `_backfill_concept_daily` | thsc_ 概念反哺(合成 OHLC) |
| `app/collector/intraday_snapshot.py:1365-1496` | 概念/extra 反哺 |
| `app/collector/index_backfill.py:601/702/781` | 多源补采(baostock/腾讯/申万) |
| `app/collector/hk_industry_backfill.py` | 港股行业 upsert |

### 2.2 消费 index_daily 的链路(读 close 计算)
| 位置 | 说明 |
|---|---|
| `app/compute/signals.py:942` `compute()` → `_load_index_ohlc_amount`(@293) | **信号计算主消费:RSI/布林/MACD,事故漏算点** |
| `app/compute/signals.py:1449` `store` | 写 signal_daily(INSERT OR REPLACE 全历史重算) |
| `scripts/signal_kelly_backtest.py:392` `_load_market_state` | hs300 MA60 大盘择时 |
| `scripts/signal_kelly_backtest.py:415` `_load_market_tiers` | hs300 四档大盘状态 |
| `scripts/signal_kelly_backtest.py:1512` `compute` | 读 signal_daily 回测 |
| `app/collector/intraday_snapshot.py:2044` `_recompute_signals` | **20:35 每轮全历史重算信号** |
| `app/collector/index_backfill.py:240` `verify_and_backfill_indices` | 唯一现有防线,只查 close 非空 + 只覆盖 10+31 |
| export 层(前端指数卡片/恐贪/per-index 情绪分) | index_daily 多展示位消费者(§22 一致性) |

### 2.3 参照既有防御模式(复用不另起炉灶)
- `app/collector/nav_placeholder_defense.py`(etf 占位判定单一来源):单哨兵 + 前后日连续判定 +
  trading_gap_between 间隔约束;SQL 侧只筛候选(CANDIDATE_WHERE),Python 侧 is_placeholder_row 统一判定。
  **新方案按同一模式:index_settlement_check.py 做「未定稿判定」单一来源。**
- `scripts/check_data_gap_alerts.py`:Finding(key 去重)+ level(warn/severe)+ 定时检测 + notify 告警
  的「标记→跳过→告警」闭环。

---

## 3. 推荐方案

### 3.1 校验位置与处理机制

**采集侧拦截(主)+ 计算侧防御(兜底)+ 定稿补采(自愈)+ 告警闭环(四件)。**

**① 新建 `app/collector/index_settlement_check.py`**(仿 nav_placeholder_defense 单一来源):
```python
# 判定单一来源
def is_unsettled_bar(open_v, high_v, low_v, close_v) -> bool:
    """OHLC 全等 = 未定稿/异常(指数历史实测 0 误伤)。任一为 None 不算(缺行语义走现有 verify)。"""
    if None in (open_v, high_v, low_v, close_v):
        return False
    eps = 1e-6
    return abs(open_v - high_v) < eps and abs(high_v - low_v) < eps and abs(low_v - close_v) < eps

# SQL 候选筛选(供 signals 计算侧兜底排除)
CANDIDATE_WHERE = "open IS NOT NULL AND open = high AND high = low AND low = close"
```

**② 采集侧拦截(防未定稿落库)**:
- `runner.py:138 upsert_index_rows`:对 `date==当前交易日` 的行先跑 is_unsettled_bar,
  **未定稿则跳过不写**(不写假 close)。返回/日志记录「未定稿跳过指数清单」。
- `intraday_snapshot.py` 三个反哺函数同样拦截(统一防线;INDEX_CODES 内虽未中招,防未来)。
- `index_backfill.py` 补采链路同理。
- 语义正确性:未定稿不落库 → signal 计算自然停在 T-1(当日无信号),等价「当日数据未到」。
  **不引入前视**(只用已定稿数据);次日定稿 upsert 覆盖 → 全历史重算 → 迟到信号自动补出(正确值)。

**③ 计算侧防御兜底(防历史遗留/漏拦截)**:
- `app/compute/signals.py:293 _load_index_ohlc_amount` 的 SQL 加
  `AND NOT (open IS NOT NULL AND open=high AND high=low AND low=close)`(或 CANDIDATE_WHERE),
  排除未定稿行参与指标计算。`signal_kelly_backtest.py:392/415` 同加。
- 目的:即使采集侧漏了/历史残留全等行,信号/回测也不吃假 close。

**④ 定稿补采(自愈,四件闭环之「定时挂载」)**:
- 挂到既有 20:35 intraday_snapshot 流程(`_recompute_signals` 之前):对「当日未定稿清单」
  重拉新浪日K,已定稿则 upsert 覆盖再算信号。9-18 实测 21:00 已定稿,20:35 是否定稿待观测
  (§5 定稿时点观测任务,跑几天后确定规律再优化时点)。
- 次日 9:25 snapshot / 9:40 kelly-rerun 流程前:对「昨日未定稿清单」重拉补采(兜底,保证次日
  信号计算用昨日定稿值)。
- 全历史重算机制已有(每次 signals.compute 全量重算 + store INSERT OR REPLACE),覆盖后自动补信号。

**⑤ 告警闭环(四件闭环之「机检 + 过期告警」)**:
- `scripts/check_data_gap_alerts.py` 新增 Finding:
  - `index_unsettled_YYYYMMDD`(warn):当日检测到 N 个指数未定稿跳过(清单附上),提示「数据源延迟,
    信号将滞后至定稿后补出」。
  - `index_unsettled_stale_YYYYMMDD`(severe):昨日未定稿清单次日仍未定稿 → 数据源故障级告警,
    需人工核查新浪发布链路。
- 用现有 notify.py --severe + dedup key(仿 signal_kelly_frozen_missing 模式)。

### 3.2 数据供给链路四件闭环(L45 教训)清单
| 件 | 落地 | 缺=不算 done |
|---|---|---|
| 生成 | index_settlement_check.py 判定函数 + 采集侧拦截 | 假 bar 仍能落库=没做成 |
| 定时挂载 | 20:35 重拉 + 次日 9:25/9:40 补采(挂既有 timer,不新增冲突) | 定稿后无机制重算=没闭环 |
| 机检 | check_data_gap_alerts 未定稿清单检测(warn) | 未定稿无告警=没人知道 |
| 过期告警 | 次日仍未定稿 → severe(notify --severe) | 数据源故障无升级告警=失守 |

### 3.3 影响面与误伤评估
- **OHLC 全等特征对指数历史 0 误伤**(实证):`sh` 全史 8728 行全等 0 行;本地近 60 日全等行仅
  9-17 事故那批 15 个(全部是未定稿假 bar)。指数是成分股集合,全天 OHLC 完全相等≈概率为 0。
  (ETF 占位 1.5 那是另一形态,已有 nav_placeholder_defense 管,别混)
- **「跳过不写」的行为变化**:未定稿当日行缺失 → 前端指数卡片/恐贪停在 T-1。已有 pending 角标
  T+1 语义(正常 T+1 就是停 T-1),展示降级兼容,但需 smoke 验证「当日缺行 → 前端正常降级」。
- **影响指数范围**:9-18 实测 15 个(6 gz_ + 4 csi_ + 2 hk_ + sz_div + csi_970070)。
  CORE_A_INDICES 10 个新浪发布及时(9-18 sh/hs300 正常行),不受影响。
- **历史数据回填**:9-17 云上已自愈(次日覆盖),本地残留 9-17 15 个全等行属开发库;9-18 云上
  15 个全等行待次日覆盖。上线后机检报告历史全等行,不建议手动改历史(等覆盖/机检兜底即可),
  避免「手动改一半」的半同步风险(§22)。

### 3.4 防前视声明
- 未定稿拦截只用「t 之前已定稿数据」判定,无未来信息。信号只能「迟到补出」,不会「用未来价回算」。
- 交叉验证(第二源确认)若用于信号,必须写明是 T 日收盘后可用(腾讯收盘价 15:00+ 才有)。

---

## 4. 举一反三(§23.3):同模式/同数据源清单

| 同模式/同源 | 现状 | 风险 | 方案覆盖 |
|---|---|---|---|
| **gz_* 国证概念(新浪)** | 无防线 | 本次事故源 | ✅ 采集侧拦截 + 补采 |
| **csi_* 中证(腾讯/新浪/csindex)** | 无防线 | 9-18 有 4 个中招 | ✅ 同上(同一拦截点) |
| **sz_div 深证红利** | 在 verify 10 核心列表但只查 close 非空 | 9-18 中招 | ✅ 同上 |
| **hk_hscci/hk_hsmpi 港股概念** | 无防线 | 9-18 中招 | ✅ 同上(新浪港股源) |
| **sw_* 申万行业** | verify 覆盖,close 非空校验 | 申万 T+1 延迟(周五周一才更)是既有已知延迟,不是假值 | ⚠ 建议 verify 对 sw 补「定稿语义」注释,无需改 |
| **thsc_* 概念(合成 OHLC)** | intraday 反哺合成 close=昨收×(1+涨幅) | **合成估算本身有未定稿风险(盘中涨幅)** | ⚠ 建议同拦截:合成 close 若 open=high=low=close 跳过 |
| **etf_daily** | nav_placeholder_defense 已覆盖 | 已有占位防御 | 不动 |
| **fund_index_daily / public_fund** | 公募 T+2 净值延迟 | 净值 T+2 定稿是既有语义 | 不动 |
| **美股隔夜 US 指数** | futures_foreign_hist | 美股盘中返回实时 bar,同源未定稿风险 | ⚠ 同拦截(collect_index 通用拦截已覆盖) |

**通用拦截点结论**:所有写 index_daily 的 upsert 入口统一走 is_unsettled_bar,一次覆盖 gz_*/csi_*/
hk_*/sz_div/thsc_* 等全部指数品类;消费侧(signals/回测)统一 CANDIDATE_WHERE 排除,双保险。

---

## 5. 实施清单(给 implementer 直接照做)

1. **新建 `app/collector/index_settlement_check.py`**:is_unsettled_bar + CANDIDATE_WHERE
   (+ settle 清单工具函数,返回当日跳过指数列表)。
2. **`app/collector/runner.py:138 upsert_index_rows`**:对当日行跑 is_unsettled_bar,未定稿跳过
   (不写),跳过清单打印/记 collect_log(metric_id=index_unsettled)。
3. **`app/collector/intraday_snapshot.py:1124/1177/1315` 三个反哺**同拦截。
4. **`app/compute/signals.py:293 _load_index_ohlc_amount`** SQL 加 CANDIDATE_WHERE 排除;
   `scripts/signal_kelly_backtest.py:392/415` 同加。
5. **`app/collector/intraday_snapshot.py:2044 _recompute_signals` 之前**加「当日未定稿清单新浪重拉」
   (已定稿则 upsert 覆盖再算信号);次日 9:25/9:40 流程对昨日清单补采。
6. **`scripts/check_data_gap_alerts.py`** 加 index_unsettled(warn)+ index_unsettled_stale(severe)。
7. **定稿时点观测**:重拉成功时打日志(YYYYMMDD index_id 定稿时点),跑 5 个交易日后汇总
   新浪对 gz_*/csi_* 的定稿时点规律,再定「20:35 vs 21:30」最终补采时点(先 20:35,观测后调整)。
8. **前端 smoke**:当日未定稿指数缺行 → 前端指数卡片/恐贪正常降级(pending 角标 T+1),不白屏。
9. **机检**:check_data_gap_alerts 能检到未定稿清单 + 次日 severe;repro/验收用
   `INSERT` 一条 OHLC 全等行 → 断言 signals 排除 + 采集拦截。

## 6. 待观测/风险(诚实标注)
- 新浪对 gz_*/csi_* 的**精确定稿时点未测**(仅在 17:50 未定稿、21:00 已定稿两点之间),用 §5.7 观测任务钉死。
- 「跳过不写」会让当日前端数据「看起来停在 T-1」,与既有「新浪延迟发布当日」的降级一致,但需 smoke 确认。
- 本方案信号会「迟到补出」(正确但晚),不能 100% 消除迟到——彻底消除需「定稿时点早于信号计算时点」,
  受数据源客观发布时点约束,方案在源客观能力内做到最早。
