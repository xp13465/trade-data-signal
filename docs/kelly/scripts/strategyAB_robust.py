# ============================================================
# 用途: 策略A/B 稳健性验证: G 模式 A vs B 在 空filter/4组合全开 下结论是否一致
# 日期/来源: 2026-08-14 / tmp
# 结论: 空filter/4组合全开下结论一致(净利 B>A, 收益率近似), 验证策略B 维持现状稳健
# 依赖: strategyAB_compare.py + kelly_combo_advice_analysis.py
# 输入/输出: 读 signal_kelly_trades.json, 输出各配置 A/B 净利/收益率/持仓对比
# 复现: python3 strategyAB_robust.py
# 注意: 原文件含硬编码绝对路径, 如需重跑请确认路径或改相对路径
# ============================================================
# -*- coding: utf-8 -*-
"""稳健性: G模式 A vs B 在 空filter / 4组合全开 下是否结论一致 (净利 B>A, 收益率近似)"""
import sys
from collections import defaultdict
sys.path.insert(0, '/tmp'); sys.path.insert(0, '/Users/linhuichen/code/trade')
from strategyAB_compare import eval_strategy, DEFAULT_NEW
from kelly_combo_advice_analysis import empty_filters
from strategyAB_compare import DAILY

FULL_AUDIT = {k: True for k in ['excludeSpecialBear','n2NovSpecialIndustry','janMidRating','janMidSpecial',
                                'n3NovSpecialMon','v4d','r8PureNonMay','greedy15']}
EMPTY = {k: False for k in empty_filters()}

print('=== 稳健性: G模式 A(固定拆K) vs B(现状等分) 空filter / 4组合全开 ===')
print('%-12s %-3s %-14s %-14s %10s %10s %10s %10s %10s' % ('配置','K','B净利','A净利','Δ净利(B-A)','B收益率%','A收益率%','B持仓','A持仓'))
for cfgname, F in [('空filter', EMPTY), ('4组合全开', FULL_AUDIT), ('AI宏7键', DEFAULT_NEW)]:
    for K in [1,2,3,4]:
        sB = eval_strategy('G', F, K, 'B')
        sA = eval_strategy('G', F, K, 'A')
        dnet = sB['net'] - sA['net']
        print('%-12s K=%d %+12.0f %+12.0f %+10.0f %10.2f %10.2f %9.0f %9.0f' % (
            cfgname, K, sB['net'], sA['net'], dnet, sB['ret'], sA['ret'], sB['peak_capital'], sA['peak_capital']))
