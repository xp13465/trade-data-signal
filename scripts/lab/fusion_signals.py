# -*- coding: utf-8 -*-
"""融合信号候选生成器（trade 专用，从 a-stock-data/backtest_strategies.py 迁出）。

依赖 a-stock-data 原有的单信号生成 gen_buy_signals / gen_sell_signals（保留在公开项目）。
本模块只提供 gen_fusion_candidates：91 个融合候选（多信号同日 AND 共振）。
"""

from backtest_strategies import gen_buy_signals, gen_sell_signals

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
