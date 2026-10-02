"""冰点认可度评分 —— 上海炒家式四因子(纯计算模块,暂不接线)。

口径照搬 docs/scripts/icepoint_bt/bt_core.py(回测定稿脚本,不做重新设计):
  F1 楼层  = a_width_max_lianban <= F1_LIMIT             (连板高度压到低位)
  F2 涨停  = a_width_zt_count   <= F2_LIMIT             (涨停数量收缩)
  F3 跌停  = a_width_dt_count   >= F3_LIMIT             (跌停数量放大)
  F4 地量  = a_amount 滚动分位(120日) <= F4_PCT          (成交低迷)

三档判定(与 bt_core.combo_flags 完全一致):
  hard   = F1 & F2 & F3 & F4
  main   = F1 & (F2 | F3) & F4
  double = 连续 2 日 main(当日 & 前一日)

F4 必须与 normalize.rolling_percentile 同函数同参数(rolling 120, min_periods=10)
且用全史序列计算(防前视,§5.1⑥):rolling rank 在 t 日只依赖 t 及之前窗口内数据。
"""
import pandas as pd

from .normalize import load_metric_series, rolling_percentile

# ============ 档位常量(集中一处,主控可在此切默认档值) ============
F1_LIMIT = 4      # F1 楼层: 连板高度 <= 4
F2_LIMIT = 40     # F2 涨停: 涨停数 <= 40
F3_LIMIT = 15     # F3 跌停: 跌停数 >= 15
F4_PCT = 30       # F4 地量: 成交额滚动 120 日分位 <= 30

# 与 normalize 同源供外部复用(模块级真实数据只在 compute() 时加载)
_METRIC_KEYS = {
    "f1": "a_width_max_lianban",
    "f2": "a_width_zt_count",
    "f3": "a_width_dt_count",
    "f4": "a_amount",
}


def _load_factor_df() -> pd.DataFrame:
    """加载四因子原始序列,merge 成一张 DataFrame。

    F4 用全史 a_amount 经 rolling_percentile(同 normalize.py:102 同参数:
    rolling(120, min_periods=10).rank(pct=True)*100)计算滚动分位,防止前视。
    """
    raw = {}
    for k, metric_id in _METRIC_KEYS.items():
        s = load_metric_series(metric_id)
        raw[k] = s.rename(k) if not s.empty else pd.Series(dtype=float, name=k)
    df = pd.DataFrame(raw)
    df["f4_pct"] = rolling_percentile(df["f4"]) if "f4" in df else pd.Series(dtype=float)
    return df


def compute():
    """返回每日四因子 bool + 明细值 + 阈值 + 共振数 + 三档判定。

    返回 DataFrame,index=date,列:
      f1_val/f2_val/f3_val/f4_pct  各因子原始值(无数据为 NaN)
      f1_hit/f2_hit/f3_hit/f4_hit  各因子 bool(无数据算未命中 False)
      f1_th/f2_th/f3_th/f4_th      各因子阈值(常量)
      n_hit                       命中口径数(0-4)
      n_avail                     当日可得口径数(值非 NaN 的口径数;历史缺楼层数据段自然降级)
      level                       三档判定: 'hard' / 'main' / 'double' / ''(未命中)
      has_signal                   main 及以上(含 hard/double)是否命中
    """
    df = _load_factor_df()
    if df.empty:
        return df

    f1_hit = df["f1"].le(F1_LIMIT) & df["f1"].notna()
    f2_hit = df["f2"].le(F2_LIMIT) & df["f2"].notna()
    f3_hit = df["f3"].ge(F3_LIMIT) & df["f3"].notna()
    f4_hit = df["f4_pct"].le(F4_PCT) & df["f4_pct"].notna()

    hard = f1_hit & f2_hit & f3_hit & f4_hit
    main = f1_hit & (f2_hit | f3_hit) & f4_hit
    double = main & main.shift(1, fill_value=False)

    out = pd.DataFrame({
        "f1_val": df["f1"],
        "f2_val": df["f2"],
        "f3_val": df["f3"],
        "f4_pct": df["f4_pct"],
        "f1_hit": f1_hit,
        "f2_hit": f2_hit,
        "f3_hit": f3_hit,
        "f4_hit": f4_hit,
        "f1_th": F1_LIMIT,
        "f2_th": F2_LIMIT,
        "f3_th": F3_LIMIT,
        "f4_th": F4_PCT,
    })
    # 共振数: 命中口径数(仅可得口径参与)
    avails = pd.DataFrame({
        "f1": df["f1"].notna(),
        "f2": df["f2"].notna(),
        "f3": df["f3"].notna(),
        "f4": df["f4_pct"].notna(),
    })
    hits = pd.DataFrame({
        "f1": f1_hit.astype(int),
        "f2": f2_hit.astype(int),
        "f3": f3_hit.astype(int),
        "f4": f4_hit.astype(int),
    })
    out["n_hit"] = hits.sum(axis=1)
    out["n_avail"] = avails.sum(axis=1)

    out["hit_hard"] = hard
    out["hit_main"] = main
    out["hit_double"] = double
    # 展示档(单值,优先级 hard > double > main;double ⊆ main 因 double=main&shift)
    level = pd.Series("", index=df.index, dtype=object)
    level.loc[main] = "main"
    level.loc[double] = "double"
    level.loc[hard] = "hard"
    out["level"] = level
    out["has_signal"] = main
    return out