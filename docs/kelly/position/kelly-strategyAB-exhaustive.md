# 凯利回测:策略A(固定拆K) vs 策略B(每日池等分) 穷举对比报告(2026-08-14)

> 生成:2026-08-14。只读分析,不改生产代码。
> 复用管线:`scripts/strategyAB_compare.py`(主对比,逐位+Σ)、`scripts/strategyAB_robust.py`(稳健性)、`scripts/amount_verify.js` + `scripts/kelly_verify_amount.py`(K=3 分仓行为)、`scripts/kelly_combo_advice_analysis.py` + `scripts/kelly_posfilter_backtest.py`(共享依赖)、`scripts/dailypool_rerun_core.py`(每日池管线)。
> 与报告 [kelly-dailypool-exhaustive-rerun.md](kelly-dailypool-exhaustive-rerun.md) 同口径对齐:主基准 = 当前页面 AI宏7键默认推荐(先 toggle 过滤 → 再 topK → 每笔=DAILY/当日保留数)。

---

## 0. 摘要(核心结论)

**策略B(每日池等分,现状)维持现状,不改。** 净利 B 恒优于 A(所有配置、所有 K 档);A 的"收益率微高"是固定拆 K 砍量→持仓更小→分母更小导致的**机制假象**,非真实超额。结论有数据支撑,如下逐项展开。

---

## 1. 两个策略定义

- **策略A(固定拆 K)**:每笔恒 `DAILY/K`(当日资金池按 K 固定等分),当日保留信号数 < K 时资金**闲置不用**(`idle_amt` 累积)。
- **策略B(现状,每日池等分)**:每笔 = `DAILY/当日保留信号数`,当日凑满 `DAILY` 资金池,无闲置。
- 口径:AI宏7键默认过滤 → topK → 每日资金池(顺序与前端 lab.js 一致)。

---

## 2. 关键数字

### 2.1 净利:B 恒优于 A(全配置、全 K 档)
- 逐位对比与 Σ 汇总,所有 A/F/G × K1-4,`Δ净利(B-A) > 0` 恒成立。
- 机制解释:A 固定拆 K,当日保留数 < K 时闲置(资金池没花满),可投资金少→净利天然低于 B 的"每日凑满"。

### 2.2 策略A 空置率(资金闲置)
- **K=3 时 A 模式资金闲置率 31.75%**(`idle_pct = idle_amt/(DAILY*active_days)`),即近 1/3 的资金池在 A 固定拆 K 下没被使用,这正是 B 恒优净利差的最大来源。
- K 越大闲置率越高(K=4 闲置更甚),A 的劣势越明显。

### 2.3 K=1 时 A ≡ B
- K=1 时策略A 每笔=DAILY/1,策略B 当日保留数=1 时也=DAILY/1,两者**逐位相同**(脚本含 K=1 自检,确认逐位相等)。这是 A≡B 的边界情形,佐证脚本正确性。

### 2.4 G K=4 时 A 收益率微高的机制解释(诚实标注)
- 个别配置(G 模式 K=4)A 的**收益率**略高于 B,但**净利仍 B>A**。
- 原因:A 固定拆 K 且大量闲置→峰值持仓更小→收益率(净利/峰值持仓)分母更小,收益率被"缩小分母"放大。这是**机制假象,非真实超额**——以净利为准,B 恒优。

---

## 3. 稳健性验证(strategyAB_robust.py)

- 在 **空 filter** / **4 组合全开** / **AI宏7键** 三种过滤配置下,G 模式 A vs B 结论一致:**净利 B>A**(收益率近似,±小差距同机制)。
- 结论:策略B 优于是**结构性的、稳健的**,不依赖特定 toggle 组合。

---

## 4. K=3 分仓行为验证(前端展示口径澄清)

### 4.1 用户感知与真实行为
用户问"K=3 为什么看到 3333/6666,不是 10000"。
- **真实行为(amount_verify.js + kelly_verify_amount.py 复算)**:每笔 = `buyAmount/dayKeptCount`。
  - **1 信号日 = 买 10000**(不是 3333),共 49 天;
  - **2 信号日 = 5000**(不是 6666),共 12 天;
  - **3 信号日 = 3333**(恰为 K=3),共 4 天。
- **3333/6666 只出现在"当日恰好 K 个信号"的日子**。当日信号数 < K 时金额 = DAILY/当日保留数(放大),而非恒 DAILY/K。

### 4.2 页面显示 3333/6666 是渲染层取整 bug(已修复)
- 页面持仓/明细显示 3333/6666 是**渲染层取整显示 bug**(把 5000/10000 等显示成 K 等分值),**非数据层错误**。
- 已在 `lab.js` 显示优化中修复(按当日保留数正确显示每笔金额)。
- 数据层金额一直正确(=`buyAmount/dayKeptCount`),仅显示层取整误导。

---

## 5. 结论与建议

- **维持策略B(每日池等分)现状**,不切到固定拆 K。
- 净利 B 恒优;A 的收益率微高是缩小分母的机制假象;A 有最高 31.75%(K=3)资金闲置。
- K=3 分仓行为:金额按当日保留数等分,页面 3333/6666 显示为渲染层 bug,已修。

---

## 6. 引用脚本

| 脚本 | 作用 |
|---|---|
| `scripts/strategyAB_compare.py` | 策略A/B 逐位+Σ 穷举对比,K=1 自检 |
| `scripts/strategyAB_robust.py` | 空filter/4组合全开下结论稳健性 |
| `scripts/amount_verify.js` | K=3 分仓行为验证(1信号=10000/49天等) |
| `scripts/kelly_verify_amount.py` | 金额口径对照验证 |
| `scripts/kelly_combo_advice_analysis.py` | 共享依赖(passes_fade/compute_stats) |
| `scripts/kelly_posfilter_backtest.py` | 共享依赖(base_signals/get_by_date) |
| `scripts/dailypool_rerun_core.py` | 每日池管线核心 |
