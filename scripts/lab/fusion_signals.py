# -*- coding: utf-8 -*-
"""融合信号候选生成器（trade 专用，从 a-stock-data/backtest_strategies.py 迁出）。

依赖 a-stock-data 原有的单信号生成 gen_buy_signals / gen_sell_signals（保留在公开项目）。
本模块只提供 gen_fusion_candidates：91 个融合候选（多信号同日 AND 共振）。
"""

from backtest_strategies import gen_buy_signals, gen_sell_signals
from backtest_strategies import rsi, ma, macd, bollinger

# 对应前端 web/lab.js _generateFusionCandidates（lab.js:669）的 91 候选：
#   - buy_sell 49：7 实验买 × 7 实验卖（与单信号配对同，buy_mask=买信号, sell_mask=卖信号）
#   - buy_buy  21：C(7,2) 双买同日 AND 共振（buy_mask = b1 & b2），卖侧用生产基线 D1_high20_drop5
#   - sell_sell 21：C(7,2) 双卖同日 AND 共振（sell_mask = s1 & s2），买侧用生产基线 C1_RSI30
# 买/卖侧的「另一侧」用生产基线固定，以隔离同向共振的效果（融合 vs 单信号增益对比）。

# 7 个实验买（zone=buy, status=experimental，对应 lab_simulate.BUY_KEYS 去掉 C1_RSI30）
FUSION_BUY_KEYS = [
    'BB_lower_revert', 'Supertrend_buy', 'Donchian20_up', 'Donchian55_up',
    'MA_golden_5_20', 'MA_golden_10_60', 'MACD_golden',
]
# 7 个实验卖（zone=sell, status=experimental，对应 lab_simulate.SELL_KEYS 去掉 D1_high20_drop5）
FUSION_SELL_KEYS = [
    'BB_upper_revert', 'MA_death_5_20', 'BB_middle_break', 'Donchian10_down',
    'Donchian20_down', 'MACD_death', 'ATR_trail_stop',
]
# 生产基线（固定另一侧，隔离同向共振效果）
REF_BUY = 'C1_RSI30'
REF_SELL = 'D1_high20_drop5'


def gen_fusion_candidates(df):
    """生成 91 个融合候选的 (pair_id, buy_mask, sell_mask, meta) 列表。

    pair_id 与前端 _generateFusionCandidates 的 _buyKey|_sellKey 对齐：
      - buy_sell: "buy_key|sell_key"
      - buy_buy:  "b1|b2"（两侧均为买 key，非标准配对 id，不与单信号 stats.json 冲突）
      - sell_sell:"s1|s2"（两侧均为卖 key）

    返回 list[dict]：{pair_id, pair_type, buy_mask, sell_mask, components, ref_side}
    """
    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)
    candidates = []

    def _mask(d, k):
        m = d.get(k)
        if m is None:
            return None
        return m.fillna(False).astype(bool)

    # 1) buy×sell 配对（49）：标准配对，buy_mask=买信号, sell_mask=卖信号
    for bk in FUSION_BUY_KEYS:
        bm = _mask(buy_signals, bk)
        if bm is None or not bm.any():
            continue
        for sk in FUSION_SELL_KEYS:
            sm = _mask(sell_signals, sk)
            if sm is None or not sm.any():
                continue
            candidates.append({
                'pair_id': f'{bk}|{sk}',
                'pair_type': 'buy_sell',
                'buy_mask': bm,
                'sell_mask': sm,
                'components': [bk, sk],
                'ref_side': None,
            })

    # 2) buy×buy 共振（21）：buy_mask = b1 & b2 同日 AND；sell_mask = 生产基线 D1
    ref_sell_mask = _mask(sell_signals, REF_SELL)
    n = len(FUSION_BUY_KEYS)
    for i in range(n):
        b1 = FUSION_BUY_KEYS[i]
        m1 = _mask(buy_signals, b1)
        if m1 is None:
            continue
        for j in range(i + 1, n):
            b2 = FUSION_BUY_KEYS[j]
            m2 = _mask(buy_signals, b2)
            if m2 is None:
                continue
            fusion_buy = m1 & m2
            sell_mask = ref_sell_mask if ref_sell_mask is not None else fusion_buy & False
            candidates.append({
                'pair_id': f'{b1}|{b2}',
                'pair_type': 'buy_buy',
                'buy_mask': fusion_buy,
                'sell_mask': sell_mask,
                'components': [b1, b2],
                'ref_side': REF_SELL,
            })

    # 3) sell×sell 共振（21）：sell_mask = s1 & s2 同日 AND；buy_mask = 生产基线 C1
    ref_buy_mask = _mask(buy_signals, REF_BUY)
    n = len(FUSION_SELL_KEYS)
    for i in range(n):
        s1 = FUSION_SELL_KEYS[i]
        m1 = _mask(sell_signals, s1)
        if m1 is None:
            continue
        for j in range(i + 1, n):
            s2 = FUSION_SELL_KEYS[j]
            m2 = _mask(sell_signals, s2)
            if m2 is None:
                continue
            fusion_sell = m1 & m2
            buy_mask = ref_buy_mask if ref_buy_mask is not None else fusion_sell & False
            candidates.append({
                'pair_id': f'{s1}|{s2}',
                'pair_type': 'sell_sell',
                'buy_mask': buy_mask,
                'sell_mask': fusion_sell,
                'components': [s1, s2],
                'ref_side': REF_BUY,
            })

    return candidates


# === 6 硬编码融合策略（与前端 web/lab.js LAB_FUSION_STRATEGIES 逐条对齐）===
# 本质 = 主信号 & 过滤条件 同日 AND（与 buy_buy/sell_sell 的 m1 & m2 取交集同构，是其扩展）。
# 过滤条件语义来自 app/compute/signals.py 生产实现（已验证对齐）。
# pair_id 用 F_ 前缀，不与 91 候选的 "a|b" 格式冲突。
#
# (pair_id, side, fusion_keys[主+过滤同日AND], ref_side另一侧固定基线)
HARDCODED_FUSIONS = [
    ('F_D1_S1_MACD',     'sell', ['D1_high20_drop5', 'MA60_bull', 'MACD_below_signal'], REF_BUY),
    ('F_D1_S1',          'sell', ['D1_high20_drop5', 'MA60_bull'],                     REF_BUY),
    ('F_B1_RSI40',       'buy',  ['BB_lower_revert', 'RSI_cross_40'],                  REF_SELL),
    ('F_B1_rebound2pct', 'buy',  ['BB_lower_revert', 'close_above_bl_2pct'],           REF_SELL),
    ('F_C1_MACD_golden', 'buy',  ['C1_RSI30', 'MACD_golden'],                          REF_SELL),
    ('F_D1_MA_death',    'sell', ['D1_high20_drop5', 'MA_death_5_20'],                 REF_BUY),
]


def _gen_filter_masks(df):
    """6 硬编码需要的 4 个过滤 mask（权威语义来自 app/compute/signals.py 生产实现）。

    - MA60_bull（状态）: close > MA60  [signals.py:367-369]
    - MACD_below_signal（状态，非穿越）: DIF < DEA  [signals.py:377]
      注: backtest 的 MACD_death@205 是穿越事件，语义不同，不能复用。
    - RSI_cross_40（穿越事件）: rp<=40 & r>40  [signals.py:345]
    - close_above_bl_2pct（状态）: close > 下轨*1.02  [signals.py:349]
      bl 与 BB_lower_revert 同源（bollinger close 20 2.0）。
    """
    close = df['close']
    out = {}
    r = rsi(close, 14)
    rp = r.shift(1)
    # MA60 多头（状态）：close > MA60  [signals.py:367-369]  ma()@90 用 min_periods=60 与生产一致
    out['MA60_bull'] = (close > ma(close, 60)).fillna(False)
    # MACD 死叉确认（状态，非穿越）：DIF < DEA  [signals.py:377]
    dif, dea = macd(close)
    out['MACD_below_signal'] = (dif < dea).fillna(False)
    # RSI 上穿 40（穿越事件）：rp<=40 & r>40  [signals.py:345]
    out['RSI_cross_40'] = ((rp <= 40) & (r > 40)).fillna(False)
    # 反弹 2%（状态）：close > 下轨*1.02  [signals.py:349]  bl 与 BB_lower_revert 同源
    _, _, bl = bollinger(close, 20, 2.0)
    out['close_above_bl_2pct'] = (close > bl * 1.02).fillna(False)
    return out


def gen_hardcoded_fusion_candidates(df):
    """6 硬编码融合候选（主信号 + 过滤条件同日 AND 取交集）。

    与 gen_fusion_candidates 同结构返回 list[dict]：
      {pair_id, pair_type, buy_mask, sell_mask, components, ref_side}
    pair_type 为 'hardcoded_buy' / 'hardcoded_sell'，pair_id 用 F_ 前缀。
    """
    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)
    filter_masks = _gen_filter_masks(df)
    all_masks = {**buy_signals, **sell_signals, **filter_masks}

    def _mask(k):
        m = all_masks.get(k)
        return m.fillna(False).astype(bool) if m is not None else None

    candidates = []
    for pair_id, side, fusion_keys, ref_side in HARDCODED_FUSIONS:
        masks = [_mask(k) for k in fusion_keys]
        if any(m is None for m in masks):
            continue
        # 同日 AND 取交集（复用 buy_buy/sell_sell 的 m1 & m2 机制，扩展到多条件）
        fusion_mask = masks[0]
        for m in masks[1:]:
            fusion_mask = fusion_mask & m
        if side == 'buy':
            buy_mask, sell_mask = fusion_mask, _mask(ref_side)
        else:
            buy_mask, sell_mask = _mask(ref_side), fusion_mask
        if buy_mask is None or sell_mask is None:
            continue
        candidates.append({
            'pair_id': pair_id,
            'pair_type': f'hardcoded_{side}',
            'buy_mask': buy_mask,
            'sell_mask': sell_mask,
            'components': fusion_keys,
            'ref_side': ref_side,
        })
    return candidates
