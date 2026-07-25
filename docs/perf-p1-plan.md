# P1-1 / P1-2 性能优化调研方案

> 纯调研报告,不改代码。基于 2026-07-25(周六)基准测试数据。
> 基准脚本:/tmp/bench-runner.py + /tmp/bench-export.py(只 compute 不 store/不 write_json,周末安全跑)

## 执行摘要

| 项 | 状态 | 当前耗时 | 进一步优化空间 | 推荐 |
|---|---|---|---|---|
| **P1-2** export.py 30次重复查DB | **已完成做透** | 2.018s | 小(~0.9s) | 暂不动 |
| **P1-1** runner.py 14步串行 | **部分完成** | 11.689s | 大(~5.7s) | 向量化3模块 |

**关键发现**:
1. **P1-2 已在 AZ11(commit a065bef9)做透**:series 内存缓存,30次重复查DB -> 5次填缓存+25次内存切片。后续 range `db=0` 命中缓存。无大优化空间。
2. **P1-1 只完成 signals.compute 向量化(AZ12 commit 455ca51c,19.6s->2.7s)**,其余12步仍串行。新瓶颈转移至 **ma_alignment 3.876s**(逐日循环 pandas .get)。
3. **a37 评审原方案"14步->ThreadPool并行"已被 a138d4a4 初判否决**(ThreadPool 对 pandas CPU 密集无效因 GIL),改走 CPU 向量化优化路径。此判断正确,本次调研延续 CPU 优化方向。
4. **最优方案 = 向量化 ma_alignment + new_high_low + cross**(像 signals 一样),预期 11.689s -> ~6s 省49%。ProcessPool 并行收益小(依赖链5.7s瓶颈)+ pickle 开销,不推荐。

---

## P1-1 runner.py 并行/优化方案

### 当前状态(已做)

| commit | 内容 | 效果 |
|---|---|---|
| 455ca51c (AZ12) | signals.compute 向量化(_supertrend/compute_band_signal numpy化 + DB批查) | 19.6s -> 2.7s 省86% |
| a138d4a4 (AZ11) | P1-1 ThreadPool 并行初判否决(回退) | - |

### 基准数据(13步串行 compute,不含 store,2026-07-25 跑)

| # | 步骤 | 耗时 | 类型 | 读表 |
|---|---|---|---|---|
| 1 | sentiment.compute | 0.205s | 依赖链 | daily_metric/index_daily -> score_daily |
| 2 | 6指数 sentiment | 0.054s(共) | 依赖链 | 同上 |
| 3 | cross.compute | **1.881s** | 依赖链 | daily_metric(归一化) -> score_daily |
| 4 | fear_greed.compute | 0.075s | 依赖链(依赖1-3) | score_daily(8 score_id) |
| 5 | signals.compute | 2.789s | 依赖链(依赖4,已优化) | score_daily+index_daily -> signal_daily |
| 6 | derived.compute | 0.038s | 独立 | daily_metric(formula) |
| 7 | ad_line.compute | 0.006s | 独立 | daily_metric |
| 8 | volume_ratio.compute | 0.114s | 独立 | daily_metric+index_daily |
| 9 | position.compute | 0.048s | 独立 | index_daily(分位) |
| 10 | signal_stats.compute | 0.735s | 依赖链(依赖5) | signal_daily |
| 11 | new_high_low.compute | **1.534s** | 独立 | index_daily |
| 12 | ma_alignment.compute | **3.876s** | 独立 | index_daily |
| 13 | rotation.compute | 0.325s | 独立 | index_daily |
| | **总计** | **11.689s** | | |

### 步骤依赖图

```
依赖链(必须串行,读 score_daily/signal_daily 上下游):
  1.sentiment(0.205) + 2.6指数(0.054) + 3.cross(1.881)
       │ store score_daily
       ▼
  4.fear_greed(0.075)  ──读 8 score_id──
       │ store score_daily(fear_greed)
       ▼
  5.signals(2.789)     ──读 fear_greed 等──
       │ store signal_daily
       ▼
  10.signal_stats(0.735) ──读 signal_daily──

依赖链总耗时:5.739s(不可并行)

独立步骤(读 index_daily/daily_metric 采集器数据,不读依赖链产物):
  6.derived(0.038)  7.ad_line(0.006)  8.volume_ratio(0.114)
  9.position(0.048)  11.new_high_low(1.534)  12.ma_alignment(3.876)
  13.rotation(0.325)
独立步骤总耗时:5.941s(可并行)
```

**关键**:独立步骤读的是采集器写入的 index_daily/daily_metric(非 runner compute 产物),与依赖链无数据依赖,理论上可并行。但依赖链 5.739s 是硬瓶颈,独立步骤并行后整体仍受限于依赖链。

### 方案 A:向量化 CPU 优化(推荐)

延续 signals.compute 向量化成功路径(AZ12),对 3 个逐行/逐日循环模块向量化:

#### A1. ma_alignment 向量化(3.876s -> ~0.3s,省3.6s)

**当前瓶颈**(`app/compute/ma_alignment.py` L59-88):
```python
for date_idx in series.index:        # 逐日循环 ~5000次
    for p in MA_PERIODS:
        v = ma[p].get(date_idx)      # pandas .get 慢(类似 signals 的 .iloc)
    if vals[5] > vals[10] > vals[20] > vals[60]:  # Python 标量比较
        alignment = "bullish"
```
8 指数 × ~5000天 × 4 MA = 16万次 pandas .get,与 signals 优化前的 .iloc 同类瓶颈。

**向量化方案**:
```python
ma5 = series.rolling(5, min_periods=5).mean().values   # numpy array
ma10 = series.rolling(10, min_periods=10).mean().values
ma20 = series.rolling(20, min_periods=20).mean().values
ma60 = series.rolling(60, min_periods=60).mean().values
bullish = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)  # numpy bool array
bearish = (ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60)
alignment = np.where(bullish, "bullish", np.where(bearish, "bearish", "cross"))
# 一次性构造 results,无逐日循环
```
MA 计算已向量化(L57 rolling),仅排列判断循环待消除。预期 <0.3s。

#### A2. new_high_low 向量化(1.534s -> ~0.2s,省1.3s)

**当前瓶颈**(`app/compute/new_high_low.py` L58-115):
```python
for date_idx in pivoted.index:       # 逐日 ~5000次
    for iid in INDICES:              # 逐指数 8次
        if close_val > prev_high_52w:  # Python 标量比较
            is_nh_52w = True
```
~5000天 × 8指数 × 4比较 = 16万次 Python 标量比较。

**向量化方案**:
```python
# rolling_high/low 已向量化(L52-55)
nh_52w = (pivoted > rolling_high_52w)    # bool DataFrame,一次完成
nl_52w = (pivoted < rolling_low_52w)
nh_52w_count = nh_52w.sum(axis=1)        # 每日总数,向量化
nl_52w_count = nl_52w.sum(axis=1)
# details 用 stacked bool 构造,无双重循环
```
预期 <0.2s。

#### A3. cross 向量化(1.881s -> ~0.4s,省1.5s)

**当前瓶颈**(`app/compute/cross.py` L46-52):
```python
def trim_mean(row):
    vals = row.dropna()
    if len(vals) < 3: return pd.NA
    return vals.sort_values().iloc[1:-1].mean()
score = df.apply(trim_mean, axis=1)   # 逐行 Python apply
```
逐行 dropna+sort+iloc,~5000行 × Python 开销。

**向量化方案**:
```python
import numpy as np
vals = df.values  # 2D numpy (date × metric)
# mask NaN,按行排序去最高最低
valid_mask = ~np.isnan(vals)
n_valid = valid_mask.sum(axis=1)
sorted_vals = np.sort(np.where(valid_mask, vals, np.nan), axis=1)
# 去最高最低:对 n_valid>=3 的行取 [1:-1] 均值
# (需按行处理有效个数,稍复杂但可 numpy 向量化)
```
预期 0.3-0.5s(比纯循环快,但 trim_mean 带 NaN 处理比 ma_alignment 略复杂)。

#### A4. signal_stats(0.735s,低优先级)

内部 `series.shift(-h)` 已向量化(L157),仅 `returns = [float(fwd_h.get(d)) for d in dates]`(L165)逐 date .get 可改 `.reindex(dates)` 批量。但在依赖链上,优化不解除瓶颈,收益小(0.735s->~0.5s),暂不动。

#### 方案 A 预期效果

| 步骤 | 优化前 | 优化后 | 省 |
|---|---|---|---|
| 3.cross | 1.881s | ~0.4s | 1.5s |
| 5.signals | 2.789s | 2.789s(已优化) | - |
| 11.new_high_low | 1.534s | ~0.2s | 1.3s |
| 12.ma_alignment | 3.876s | ~0.3s | 3.6s |
| **13步总计** | **11.689s** | **~6.0s** | **~5.7s(49%)** |

优化后依赖链 = sentiment(0.205)+6指数(0.054)+cross(0.4)+fear_greed(0.075)+signals(2.789)+signal_stats(0.735) = **4.258s**(新瓶颈,signals 2.789s 占65%)

### 方案 B:ProcessPool 并行独立步骤(不推荐)

- 独立步骤 5.941s 并行 -> max(ma_alignment 3.876s) = 3.876s,省 2.065s
- 但依赖链 5.739s 不可并行,整体 -> 5.739s
- **ProcessPool 开销**:每进程加载 python+import pandas+DB连接 ~1-2s,pickle 大对象(signals 49701个)序列化开销
- **净收益**:2.065s - 1~2s 开销 ≈ 0~1s,且风险高
- **风险**:进程隔离 DB 连接/pickle 失败/内存翻倍每进程一份/进度文件 race

### 方案 C:A + B 组合(无额外收益)

- 先 A 向量化:11.689s -> ~6s(依赖链 4.258s 瓶颈)
- 再 B 并行:独立步骤 max(rotation 0.325s) 并行无意义,依赖链 4.258s 仍瓶颈
- **结论**:A 后 B 无额外收益,依赖链是硬瓶颈

### P1-1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 向量化结果不一致 | 数据错误 | 逐模块 STRICT MATCH 验证(像 signals 455ca51c 的 49701 vs 49701 双向零差异) |
| numpy NaN 边界 | 少量边界值偏差 | 保留 min_periods 逻辑,边界 case 单测 |
| cross trim_mean NaN 处理 | 去最高最低逻辑偏差 | 对 n_valid<3 行返 NA(同原逻辑),向量化用 mask |

### P1-1 实施步骤(用户定后)

1. **ma_alignment 向量化**(独立模块,可先做)
   - 改 `app/compute/ma_alignment.py` L46-88
   - 基准:3.876s -> <0.5s
   - 验证:对比 data 输出 STRICT MATCH(8指数×5000天 alignment + ma 值)
2. **new_high_low 向量化**(独立模块)
   - 改 `app/compute/new_high_low.py` L58-115
   - 基准:1.534s -> <0.3s
   - 验证:对比 data 输出 STRICT MATCH(nh/nl counts + details)
3. **cross 向量化**(依赖链上,但优化不改依赖)
   - 改 `app/compute/cross.py` L46-52
   - 基准:1.881s -> <0.5s
   - 验证:对比 score_series + components_df STRICT MATCH
4. **端到端 runner.run() 基准**:11.689s -> ~6s 目标
5. 不需 deploy(后端 compute 速度,输出 100% 一致,前端 JSON 无变化)

---

## P1-2 export.py 内存切片方案

### 当前状态(已完成做透)

| commit | 内容 | 效果 |
|---|---|---|
| a065bef9 (AZ11) | series 内存缓存(_series_cache) | 30次重复查DB -> 5次+25次切片 |
| 329c1ce8 (AZ13) | queries.py 共享层重构 | 消除 DRY 违反,export 包缓存层 |

### 基准数据(5tab×6range,不含 write_json/gzip/R2,2026-07-25 跑)

```
_series_cache 初始: 0 keys
  a-stock-3m    0.154s  db=44   <- 填缓存
  a-stock-6m    0.004s  db=0    <- 命中缓存(内存切片)
  a-stock-1y    0.004s  db=0    <- 命中缓存
  a-stock-3y    0.004s  db=0
  a-stock-5y    0.004s  db=0
  a-stock-all   0.005s  db=0
  hk-3m         0.776s  db=20   <- 填缓存
  hk-6m~all     0.002s  db=0    <- 命中缓存
  global-3m     0.128s  db=32   <- 填缓存
  global-6m~all 0.003s  db=0    <- 命中缓存
  sentiment-3m  0.094s  db=18   <- 填缓存
  sentiment-6m~all 0.001s db=0  <- 命中缓存
  industry-3m   0.727s  db=240  <- 填缓存(31行业×8query)
  industry-6m   0.045s  db=31   <- 部分新 id
  industry-1y   0.042s  db=31
_series_cache 终态: 323 keys
5tab×6range 总耗时: 2.018s
```

**缓存完全生效**:每 tab 第一个 range(3m)查 DB 填缓存,后续 5 个 range `db=0` 命中缓存内存切片。30 次重复查 DB 降至 5 次填缓存 + 25 次内存切片。

### 剩余小优化(收益小,可选)

#### 1. industry 批查(0.727s -> ~0.3s,省0.4s)

**当前**:`industry-3m` 查 240 次 DB(31 行业 × ~8 query:width+index+signals等),逐行业分别查。
**优化**:industry_width 可一次查所有行业(`SELECT ... WHERE industry_code IN (...)`),减少 240 -> ~8 次。
**收益**:省 ~0.4s,但 industry 拆分逻辑复杂,改动风险中等。

#### 2. etf_national_team 缓存(0.66s -> ~0.1s,省0.5s)

**当前**:6 range × 0.11s = 0.66s,不走 `_series_cache`(有自己的 export_data),每次重算切片。
**优化**:`export_etf_national_team` 内部对 _nt_daily 按 range 字符串切片(同 series_cache 模式)。
**收益**:省 ~0.5s。

#### 3. index/{id}-all.json(0.4s,已快)

93 个指数,前10个 0.045s,全部 ~0.4s。series_cache 命中,无优化空间。

### P1-2 结论

**已完成做透,无大优化空间**。series 缓存(a065bef9)+ queries 重构(329c1ce8)已将 30 次重复查 DB 降至 5 次填缓存+25 次内存切片。端到端 2.018s。

剩余小优化(industry 批查 + etf_nt 缓存)共省 ~0.9s,收益小且改动风险,建议暂不动。若要做,优先 etf_nt 缓存(简单低风险)。

---

## 优先级推荐 + 总预期提速

### 优先级

| 优先级 | 项 | 预期省时 | 风险 | 工作量 |
|---|---|---|---|---|
| **P1**(先做) | P1-1 A1 ma_alignment 向量化 | 3.6s | 低(独立模块) | 中 |
| **P2** | P1-1 A2 new_high_low 向量化 | 1.3s | 低(独立模块) | 中 |
| **P3** | P1-1 A3 cross 向量化 | 1.5s | 低(依赖链但输出一致) | 中 |
| 暂不动 | P1-2 剩余小优化 | 0.9s | 中(industry复杂) | 中 |
| 不做 | P1-1 B ProcessPool 并行 | 0~1s | 高(pickle/内存) | 高 |

### 推荐执行顺序

1. **先做 P1-1 A1(ma_alignment)**:单模块最大收益(3.6s),独立无依赖,风险最低
2. **再做 P1-1 A2(new_high_low)**:同模式向量化,收益 1.3s
3. **最后 P1-1 A3(cross)**:trim_mean 向量化稍复杂,收益 1.5s
4. **P1-2 暂不动**:已做透,剩余小优化收益不抵风险

### 总预期提速

| 场景 | 当前 | 优化后 | 省 |
|---|---|---|---|
| runner.run() compute(不含 store) | 11.689s | ~6.0s | 5.7s(49%) |
| runner.run() 端到端(含 store,AZ12 记13.16s) | ~13.2s | ~7.5s | 5.7s(43%) |
| export.py main(5tab×6range) | 2.018s | 2.018s(不动) | 0 |
| **update_all core pipeline 总耗时** | 参考 pipeline_core 17:50->18:11=~21min | 省约5-6s(compute占比小,采集占大头) | <1% |

**注意**:update_all 总耗时主要受采集(mootdx/baostock 网络IO)和 deploy(git/rsync/R2)主导,compute+export 仅占 ~15s/21min=~1%。P1-1 优化对 update_all 总耗时提升 <1%,但对**单个 compute 任务执行速度**提升 49%(符合⑤提速=单个任务执行速度非一天总耗时)。

### 验证口径

1. P1-1 各模块向量化后 STRICT MATCH 100%(逐元素有序比较,像 signals 455ca51c)
2. P1-1 端到端 runner.run() 耗时基准(目标 <7s)
3. P1-2 不动,维持当前 2.018s
4. 代码改动 git diff 仅限 3 个 compute 模块(ma_alignment/new_high_low/cross)

---

## 附录:基准测试方法

**脚本**:/tmp/bench-runner.py + /tmp/bench-export.py(周末安全跑,只 compute 不 store/不 write_json)
**环境**:cwd=/Users/linhuichen/code/trade-data(§9 读最新主库),python=/Users/linhuichen/code/trade/.venv/bin/python
**日期**:2026-07-25(周六,非交易日,DB 数据为 07-24 收盘)
**可复现**:`/Users/linhuichen/code/trade/.venv/bin/python /tmp/bench-runner.py`

**P1-1/P1-2 历史闭环**(AZ11/AZ12/AZ13,2026-07-24~25):
- a065bef9: P1-2 series 缓存(30次查DB->5次+25次切片)
- 455ca51c: P1-1 signals 向量化(19.6s->2.7s)
- 329c1ce8: queries.py 共享层重构(消除 DRY)
- 本次调研 = 在已闭环基础上,找剩余优化空间(ma_alignment 新瓶颈)
