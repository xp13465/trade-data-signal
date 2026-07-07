"""§7 买点/卖点：买=RSI 事件化（C1），卖=20日高回落5%（D1 high-based）。

买点（C1，2026-07-06 验收通过，不动）：RSI(14) 上穿 30 为主信号，cross 降为情绪分级
标签写进 reason 供参考。
- 买点 = RSI(14) 上穿 30（前一日≤30 且当日>30，超卖结束、有望反弹）

卖点（D1，2026-07-06 改）：close 从近 20 日最高价（high-based）回落 5%。
- 卖点 = 前一日 close ≥ 阈 且 当日 close < 阈（阈 = 近20日 high 之 max × 0.95）
- 定位：趋势转弱/止盈减仓提示（非做空/反向信号；回测显示任何卖点都难有高胜率，
  D1 是测试方案中"最不坏的"，2016+ 10日胜率 50.6%/盈亏比 1.04，唯一达标）。

事件化：只在「穿越」那一天标，一次连续超卖/超买期只产 1 个点
（RSI 反复进出超卖/超买区则每次退出各 1 个点，算独立事件）。

cross 不再作硬门槛过滤，而是分级标签附在 reason 末尾供参考：
<30 冰点 / 30-50 偏冷 / 50-70 中性 / 70-80 偏热 / >=80 狂热。

阈值定义（语义）：
- 买触发 rsi_prev<=30 且 rsi>30：前一日在超卖区（含边界）、当日升回 30 之上 = 超卖结束
- 卖触发 close_prev>=thresh 且 close<thresh：前一日还在阈之上、当日跌破阈 = 趋势转弱

C1 变更（2026-07-06）：原 E1 逻辑要求买 cross<30、卖 cross>70 作共振硬门槛，
近年市场宽度结构变化致 cross 多在 30-70 中性区，近端买点长期 0、卖点也偏少。
改为 RSI 事件为主、cross 软分级标签化，恢复信号可用性。

D1 变更（2026-07-06）：C1 卖点用 RSI 下穿70，回测显示全史 10日胜率仅 43.1%/盈亏比
0.76/均值 +1.29%（信号后价格仍涨，方向相反），是最差的卖点。改 D1=20日高回落5%
（high-based），2016+ 10日胜率 50.6%/盈亏比 1.04，是回测 12 方案中唯一在 2016+
窗口达标的卖点。RSI 在卖点降级为参考标签附在 reason（不作触发）；买点 RSI 不动。

方案 B 标注（2026-07-06）：卖点 reason 附 `vs前买{±X.XX%}[分类]` 标签，标注相对
最近一次前置买点 close 的盈亏，便于用户判断卖点质量与操作建议。**只加标注，不改
触发条件**（买点 C1 + 卖点 D1 触发逻辑不动，信号数不变）。
- 维护 `last_buy_close` 游标（每个 index_id 独立，按 date 升序遍历）：遇到 buy 信号
  时更新 last_buy_close=该买点 close。
- 卖点触发时：close > 前买点 close → `vs前买+X.XX%[止盈]`（前端绿）；close < 前买点
  close → `vs前买-X.XX%[买点失败]`（前端灰，操作建议止损观望）；窗口内无前置买点
  → `无前买点[趋势中]`（前端橙）。
- 例：`20日高回落5%(高8864->阈8421,close8300), RSI=33, cross=55[中性], vs前买-2.32%[买点失败]`
"""
import pandas as pd

from .normalize import load_index_close, load_index_high, load_metric_value, load_score_value
from ..collector.fetchers import load_config
from ..db import get_conn


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def _cross_tag(cross_val) -> str:
    """cross 分级标签：<30 冰点 / 30-50 偏冷 / 50-70 中性 / 70-80 偏热 / >=80 狂热。

    NaN 返回空串（调用方 reason 拼接时省略 cross 段）。
    """
    if pd.isna(cross_val):
        return ""
    v = float(cross_val)
    if v < 30:
        return "冰点"
    if v < 50:
        return "偏冷"
    if v < 70:
        return "中性"
    if v < 80:
        return "偏热"
    return "狂热"


def _load_cross_score() -> pd.Series:
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, value FROM score_daily WHERE score_id='cross_market' ORDER BY date"
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["value"] for r in rows}).sort_index().astype(float)


# ============ B 扩展：全球指标 + 情绪分数买卖点（2026-07-07）============
# value 当 close 算 RSI 买 + 20日高回落卖，规则按 09-指标买卖点回测.md 推荐：
#   买 = RSI(14) 上穿 30（与指数 C1 一致）
#   卖分支：恒正序列（min>0）用 %回落5%（thresh=hh20*0.95）；
#           含负数/窄幅序列用 std 2σ（thresh=hh20-2.0*std20）。
# a_sentiment 买规则失效（RSI 结构性≥40，0 信号）→ skip_buy，仅算卖。
# signal_daily index_id 前缀：g.<metric_id> / s.<score_id>（区分指数/指标/分数）。
# 卖点 reason 附 vs前买 标注，分母用 |last_buy_value| 兼容负数序列（如 cn_us_spread）。
GLOBAL_METRIC_IDS = (
    "cn10y", "us10y", "wti_oil", "comex_silver", "gold", "oil",
    "usdcnh", "a_qvix_300", "a_qvix_1000", "cn_us_spread",
)
SCORE_IDS = ("cross_market", "a_sentiment")
# 窄幅序列（虽恒正但 %回落 0 信号，回测验证）+ 含负数序列 → 强制走 std 卖规则
_STD_SELL_IDS = {"usdcnh", "cn_us_spread"}


def _compute_value_signals(value: pd.Series, sid: str, skip_buy: bool = False, kind: str = "指标"):
    """value 序列 → 买卖点 signals（sid 已含 g./s. 前缀）。

    value: pd.Series（按 date 升序，float），当 close 用
    sid: signal_daily index_id（如 'g.cn10y' / 's.cross_market'）
    skip_buy: True 时跳过买信号（a_sentiment 用，RSI 失效）
    kind: reason 标签（"指标"/"情绪分"），区分指数 signals
    """
    if len(value) < 30:
        return []
    rsi = _rsi(value, 14)
    rsi_prev = rsi.shift(1)

    # 买点（C1 一致）：RSI 上穿 30；skip_buy 时全 False
    if skip_buy:
        buy = pd.Series(False, index=value.index)
    else:
        buy = ((rsi_prev <= 30) & (rsi > 30)).fillna(False)

    # 卖点分支：恒正（min>0）且非窄幅 → %回落5%；否则（含负数/窄幅）→ std 2σ
    raw = sid.split(".", 1)[1] if "." in sid else sid
    use_std = (raw in _STD_SELL_IDS) or not (value.min() > 0)
    hh20 = value.rolling(20).max()
    if use_std:
        std20 = value.rolling(20).std()
        thresh = hh20 - 2.0 * std20
        sell_label = "20日高回落2σ"
    else:
        thresh = hh20 * 0.95
        sell_label = "20日高回落5%"
    sell = ((value.shift(1) >= thresh.shift(1)) & (value < thresh)).fillna(False)

    # B 标注（vs前买）：分母用 |last_buy_value| 兼容负数序列
    buy_set = set(buy[buy].index)
    sell_set = set(sell[sell].index)
    out = []
    last_buy_value = None
    for date in sorted(buy_set | sell_set):
        v = value.get(date)
        if date in buy_set:
            last_buy_value = float(v) if pd.notna(v) else last_buy_value
            r = rsi.get(date)
            rp = rsi_prev.get(date)
            reason = f"RSI上穿30({rp:.0f}->{r:.0f})" if pd.notna(r) and pd.notna(rp) else "RSI=NA"
            reason += f",[{kind}]"
            out.append((date, sid, "buy", reason))
        if date in sell_set:
            h = hh20.get(date)
            t = thresh.get(date)
            parts = []
            if pd.notna(h) and pd.notna(t) and pd.notna(v):
                parts.append(f"{sell_label}(高{h:.4g}->阈{t:.4g},value{v:.4g})")
            else:
                parts.append(sell_label)
            rv = rsi.get(date)
            if pd.notna(rv):
                parts.append(f"RSI={rv:.0f}")
            # vs前买 标注：分母 |last_buy_value| 兼容负数（cn_us_spread 可 -3~2）
            if last_buy_value is not None and pd.notna(v):
                denom = abs(last_buy_value)
                if denom > 0:
                    pct = (float(v) - last_buy_value) / denom * 100
                    sign = "+" if pct >= 0 else ""
                    tag = "止盈" if pct > 0 else "买点失败"
                    parts.append(f"vs前买{sign}{pct:.2f}%[{tag}]")
                else:
                    parts.append("无前买点[趋势中]")
            else:
                parts.append("无前买点[趋势中]")
            parts.append(f"[{kind}]")
            out.append((date, sid, "sell", ", ".join(parts)))
    return out


def compute():
    cfg = load_config()
    cross = _load_cross_score()
    signals = []
    for idx in cfg.get("indices", []):
        if not idx.get("enabled", True):
            continue
        iid = idx["id"]
        close = load_index_close(iid)
        if len(close) < 30:
            continue
        high = load_index_high(iid).reindex(close.index)  # high 对齐 close，缺失前向无填充
        rsi = _rsi(close, 14)
        cross_aligned = cross.reindex(close.index)
        rsi_prev = rsi.shift(1)

        # 买点（C1，不动）：RSI 上穿 30 事件化；首日 shift 出 NaN，fillna(False) 跳过。
        # cross 不再作硬门槛，仅作分级标签写进 reason。
        buy = ((rsi_prev <= 30) & (rsi > 30)).fillna(False)

        # 卖点（D1，high-based 20 日回落 5%）：close 从近 20 日最高价（用 high 不用 close）
        # 回落 5% = 趋势转弱/止盈减仓提示。事件化：前一日还在阈之上、当日跌破阈才标。
        # high-based 比	close-based 2016+ 10日胜率高 5pp（50.6% vs 45.6%，回测验证）。
        hh20 = high.rolling(20).max()
        thresh = hh20 * 0.95
        sell = ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)

        # 方案 B 标注（2026-07-06）：卖点 reason 附 vs前买 标签 + 分类（止盈/买点失败/无前买点）。
        # 维护 last_buy_close 游标（每个指数独立，按 date 升序遍历）：
        #   - 遇到 buy 信号：更新 last_buy_close = 该买点 close
        #   - 遇到 sell 信号：若 last_buy_close 存在，算 pct=(close-last_buy_close)/last_buy_close*100，
        #     pct>0 → 止盈；pct<=0 → 买点失败；若 last_buy_close 不存在 → 无前买点(趋势中)。
        # **买点 C1 + 卖点 D1 触发逻辑不动**（只加标注，不改触发条件，信号数不变）。
        buy_set = set(buy[buy].index)
        sell_set = set(sell[sell].index)
        last_buy_close = None  # 游标：最近一次买点 close（None=窗口内无前置买点）
        for date in sorted(buy_set | sell_set):
            if date in buy_set:
                # 买点（C1，不动）：RSI 上穿 30 事件化；reason 不变。
                last_buy_close = float(close.get(date)) if pd.notna(close.get(date)) else last_buy_close
                r = rsi.get(date)
                rp = rsi_prev.get(date)
                reason = f"RSI上穿30({rp:.0f}->{r:.0f})" if pd.notna(r) and pd.notna(rp) else "RSI=NA"
                cv = cross_aligned.get(date)
                if pd.notna(cv):
                    reason += f",cross={cv:.0f}[{_cross_tag(cv)}]"
                signals.append((date, iid, "buy", reason))
            if date in sell_set:
                # 卖点（D1，触发逻辑不动）：close 从近 20 日 high 之 max 回落 5%。
                h = hh20.get(date)
                t = thresh.get(date)
                c = close.get(date)
                r = rsi.get(date)
                parts = []
                if pd.notna(h) and pd.notna(t) and pd.notna(c):
                    parts.append(f"20日高回落5%(高{h:.0f}->阈{t:.0f},close{c:.0f})")
                else:
                    parts.append("20日高回落5%")
                if pd.notna(r):
                    parts.append(f"RSI={r:.0f}")  # RSI 降级为参考标签，不作触发
                cv = cross_aligned.get(date)
                if pd.notna(cv):
                    parts.append(f"cross={cv:.0f}[{_cross_tag(cv)}]")  # cross 软分级参考
                # vs前买 标注（方案 B）：按 close vs last_buy_close 分类
                if last_buy_close is not None and pd.notna(c):
                    pct = (float(c) - last_buy_close) / last_buy_close * 100
                    sign = "+" if pct >= 0 else ""
                    tag = "止盈" if pct > 0 else "买点失败"
                    parts.append(f"vs前买{sign}{pct:.2f}%[{tag}]")
                else:
                    parts.append("无前买点[趋势中]")
                signals.append((date, iid, "sell", ", ".join(parts)))

    # B 扩展：全球指标 + 情绪分数 signals（value 当 close，按 09 回测推荐规则）
    for mid in GLOBAL_METRIC_IDS:
        value = load_metric_value(mid)
        if value.empty:
            continue
        signals.extend(_compute_value_signals(value, f"g.{mid}", kind="指标"))
    for scid in SCORE_IDS:
        value = load_score_value(scid)
        if value.empty:
            continue
        signals.extend(_compute_value_signals(value, f"s.{scid}", skip_buy=(scid == "a_sentiment"), kind="情绪分"))

    return signals


def store(signals) -> int:
    conn = get_conn()
    conn.execute("DELETE FROM signal_daily")  # 信号逻辑变更，清空重算
    conn.executemany(
        "INSERT INTO signal_daily (date, index_id, signal, reason) VALUES (?,?,?,?)",
        signals,
    )
    conn.commit()
    conn.close()
    return len(signals)
