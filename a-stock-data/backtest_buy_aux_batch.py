"""buy_aux（B1 辅买）逐品类优化回测 — 批量品类版（泛化）。

家电（sw_801110）打样 + 商贸（sw_801200）已分别测过（14/15 报告）。
本脚本泛化支持品类列表，循环跑 3 个行业品类（电力设备 / 轻工 / 基础化工），
每品类独立判断（不套同一方案），全史 10d 主 horizon + 5d/20d 验证。

数据源：data/sentiment.db
  - index_daily（{SID} 的 date/open/high/low/close/amount）
  - amount 列作 volume 代理（成交金额，比 volume 更能反映资金进场）

复刻 app/compute/signals.py（与 backtest_buy_aux_optimize.py / sw801200.py 完全一致）：
  - RSI(14) EWM α=1/14 adjust=False
  - BB(20, 2.0) std ddof=0
  - buy_aux B1 = (close_prev < bl_prev) & (close > bl)，fillna(False)
  - C1 主买 = RSI 上穿 30（用于去重：buy_aux_set - buy_set，C1 优先）

方案（与家电/商贸一致，横向可比）：
  A_反弹力度2%  — 反弹力度确认（close > bl × 1.02，过滤 barely-crossed 假信号）
  B_RSI上穿40   — RSI 动量确认（BB下轨回归 + RSI 上穿 40，价格+动量双确认）
  C_放量1.2倍   — 放量确认（BB下轨回归 + amount > 5日均量 × 1.2，资金进场确认）

凯利：f* = max(0, (b·p - (1-p))/b)，p=胜率 b=盈亏比。买点胜率=收益>0占比。
n<10 = 样本不足，n<30 = 样本不足警示。

约束：独立复刻，不 import app，不改 app/ 代码，不改 DB。
"""
import sqlite3
import sys
import numpy as np
import pandas as pd

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
# REPORT 路径根据品类列表动态生成（命令行调用时按 sid 拼接文件名）
REPORT = None  # 在 main() 里按品类拼接
HORIZONS = [5, 10, 20]
PRIMARY_HORIZON = 10  # 主指标，与前端 tips 一致
KELLY_INSUF_N = 10
SAMPLE_WARN_N = 30

# 待测品类列表（可命令行覆盖）
DEFAULT_CATEGORIES = [
    ('sw_801760', '传媒'),
    ('sw_801230', '综合'),
    ('sw_801040', '钢铁'),
]

# 家电 / 商贸 / 电力设备 / 轻工 / 基础化工 已测结果，用于 8 品类横向对比汇总
# 结构: {sid: {scheme: {horizon: (n, mean_pct, wr, pl, f, lbl)}}}
PRIOR_CATEGORIES = {
    'sw_801110': {
        'name': '家电',
        'baseline': {
            5: (135, -0.14, 0.519, 0.84, -0.0528, '不建议'),
            10: (134, -1.23, 0.448, 0.66, -0.3854, '不建议'),
            20: (133, -0.47, 0.504, 0.84, -0.0857, '不建议'),
        },
        'A_反弹力度2%': {
            5: (18, -1.35, 0.500, 0.51, -0.4808, '不建议'),
            10: (18, -4.68, 0.222, 0.57, -1.1460, '不建议'),
            20: (18, -1.49, 0.444, 0.80, -0.2514, '不建议'),
        },
        'B_RSI上穿40': {
            5: (33, +0.53, 0.667, 0.70, +0.1912, '建议'),
            10: (33, +0.54, 0.545, 1.19, +0.1619, '建议'),
            20: (33, +1.16, 0.545, 1.21, +0.1711, '建议'),
        },
        'C_放量1.2倍': {
            5: (8, -1.17, 0.750, 0.19, -0.5784, '样本不足'),
            10: (8, -0.14, 0.500, 0.94, -0.0323, '样本不足'),
            20: (8, +2.24, 0.625, 1.29, +0.3349, '样本不足'),
        },
        'n_signals': {'基线_B1': 135, 'A_反弹力度2%': 18, 'B_RSI上穿40': 33, 'C_放量1.2倍': 8},
    },
    'sw_801200': {
        'name': '商贸',
        'baseline': {
            5: (165, -0.52, 0.455, 0.81, -0.2155, '不建议'),
            10: (164, -1.19, 0.433, 0.75, -0.3187, '不建议'),
            20: (164, -1.36, 0.421, 0.88, -0.2367, '不建议'),
        },
        'A_反弹力度2%': {
            5: (22, +0.06, 0.500, 1.03, +0.0160, '建议'),
            10: (22, -0.43, 0.455, 1.02, -0.0787, '不建议'),
            20: (22, +0.46, 0.409, 1.62, +0.0442, '建议'),
        },
        'B_RSI上穿40': {
            5: (35, -0.94, 0.429, 0.71, -0.3811, '不建议'),
            10: (35, -1.46, 0.457, 0.64, -0.3922, '不建议'),
            20: (35, -1.37, 0.343, 1.29, -0.1667, '不建议'),
        },
        'C_放量1.2倍': {
            5: (7, -1.86, 0.143, 1.25, -0.5419, '样本不足'),
            10: (7, -3.30, 0.429, 0.29, -1.5539, '样本不足'),
            20: (7, -1.22, 0.429, 0.97, -0.1610, '样本不足'),
        },
        'n_signals': {'基线_B1': 165, 'A_反弹力度2%': 22, 'B_RSI上穿40': 35, 'C_放量1.2倍': 7},
    },
    # 电力设备 / 轻工 / 基础化工 来自 16 报告（2026-07-05 回测）
    'sw_801730': {
        'name': '电力设备',
        'baseline': {
            5: (59, -0.64, 0.542, 0.59, -0.2392, '不建议'),
            10: (59, -1.24, 0.458, 0.76, -0.2548, '不建议'),
            20: (58, -0.71, 0.448, 0.98, -0.1125, '不建议'),
        },
        'A_反弹力度2%': {
            5: (10, -0.08, 0.500, 0.97, -0.0159, '不建议'),
            10: (10, +1.34, 0.600, 1.02, +0.2085, '建议'),
            20: (9, +2.28, 0.667, 0.91, +0.2984, '样本不足'),
        },
        'B_RSI上穿40': {
            5: (10, -0.60, 0.600, 0.47, -0.2485, '不建议'),
            10: (10, +0.57, 0.500, 1.24, +0.0969, '建议'),
            20: (10, +0.75, 0.500, 1.24, +0.0961, '建议'),
        },
        'C_放量1.2倍': {
            5: (1, +6.73, 1.000, None, None, '样本不足'),
            10: (1, +13.36, 1.000, None, None, '样本不足'),
            20: (1, +12.49, 1.000, None, None, '样本不足'),
        },
        'n_signals': {'基线_B1': 59, 'A_反弹力度2%': 10, 'B_RSI上穿40': 10, 'C_放量1.2倍': 1},
    },
    'sw_801140': {
        'name': '轻工制造',
        'baseline': {
            5: (161, +0.00, 0.528, 0.90, +0.0009, '建议'),
            10: (160, -1.04, 0.450, 0.79, -0.2496, '不建议'),
            20: (160, -0.56, 0.450, 1.03, -0.0816, '不建议'),
        },
        'A_反弹力度2%': {
            5: (19, +0.46, 0.579, 0.92, +0.1197, '建议'),
            10: (19, -2.76, 0.421, 0.59, -0.5619, '不建议'),
            20: (19, +0.94, 0.526, 1.13, +0.1057, '建议'),
        },
        'B_RSI上穿40': {
            5: (38, +0.01, 0.553, 0.81, +0.0020, '建议'),
            10: (38, -0.56, 0.500, 0.78, -0.1412, '不建议'),
            20: (38, -0.03, 0.500, 0.99, -0.0052, '不建议'),
        },
        'C_放量1.2倍': {
            5: (12, -0.42, 0.250, 2.24, -0.0852, '不建议'),
            10: (12, -3.51, 0.333, 0.48, -1.0537, '不建议'),
            20: (12, -5.02, 0.250, 0.63, -0.9480, '不建议'),
        },
        'n_signals': {'基线_B1': 161, 'A_反弹力度2%': 19, 'B_RSI上穿40': 38, 'C_放量1.2倍': 12},
    },
    'sw_801030': {
        'name': '基础化工',
        'baseline': {
            5: (160, -0.36, 0.481, 0.84, -0.1350, '不建议'),
            10: (160, -0.81, 0.425, 0.91, -0.2087, '不建议'),
            20: (160, -0.51, 0.500, 0.84, -0.0919, '不建议'),
        },
        'A_反弹力度2%': {
            5: (19, +1.04, 0.526, 1.64, +0.2377, '建议'),
            10: (19, +1.26, 0.579, 1.12, +0.2043, '建议'),
            20: (19, +2.40, 0.579, 1.36, +0.2694, '建议'),
        },
        'B_RSI上穿40': {
            5: (30, -0.04, 0.467, 1.12, -0.0107, '不建议'),
            10: (30, -1.14, 0.367, 1.12, -0.1995, '不建议'),
            20: (30, -1.82, 0.367, 1.01, -0.2631, '不建议'),
        },
        'C_放量1.2倍': {
            5: (9, -0.21, 0.444, 1.08, -0.0704, '样本不足'),
            10: (9, -1.78, 0.444, 0.64, -0.4253, '样本不足'),
            20: (9, -2.47, 0.556, 0.39, -0.5918, '样本不足'),
        },
        'n_signals': {'基线_B1': 160, 'A_反弹力度2%': 19, 'B_RSI上穿40': 30, 'C_放量1.2倍': 9},
    },
    # sh / csi1000 / hs300 来自 17 报告（2026-07-05 回测，A股宽基）
    'sh': {
        'name': '上证指数',
        'baseline': {
            5: (185, -0.66, 0.438, 0.80, -0.2619, '不建议'),
            10: (185, -0.64, 0.389, 1.19, -0.1251, '不建议'),
            20: (184, -0.76, 0.446, 1.00, -0.1114, '不建议'),
        },
        'A_反弹力度2%': {
            5: (26, -0.95, 0.423, 0.88, -0.2329, '不建议'),
            10: (26, +1.53, 0.385, 2.19, +0.1038, '建议'),
            20: (26, +1.45, 0.423, 1.73, +0.0893, '建议'),
        },
        'B_RSI上穿40': {
            5: (44, -0.84, 0.432, 0.66, -0.4270, '不建议'),
            10: (44, -1.25, 0.409, 0.85, -0.2891, '不建议'),
            20: (43, -1.03, 0.512, 0.71, -0.1807, '不建议'),
        },
        'C_放量1.2倍': {
            5: (0, None, None, None, None, '样本不足'),
            10: (0, None, None, None, None, '样本不足'),
            20: (0, None, None, None, None, '样本不足'),
        },
        'n_signals': {'基线_B1': 185, 'A_反弹力度2%': 26, 'B_RSI上穿40': 44, 'C_放量1.2倍': 0},
    },
    'csi1000': {
        'name': '中证1000',
        'baseline': {
            5: (71, -0.08, 0.620, 0.58, -0.0331, '不建议'),
            10: (71, -0.77, 0.493, 0.74, -0.1950, '不建议'),
            20: (70, -0.26, 0.514, 0.87, -0.0468, '不建议'),
        },
        'A_反弹力度2%': {
            5: (6, +0.48, 0.667, 0.65, +0.1552, '样本不足'),
            10: (6, +1.58, 0.667, 0.74, +0.2167, '样本不足'),
            20: (5, +7.89, 1.000, None, None, '样本不足'),
        },
        'B_RSI上穿40': {
            5: (19, +0.49, 0.737, 0.50, +0.2093, '建议'),
            10: (19, +0.15, 0.474, 1.20, +0.0347, '建议'),
            20: (18, +1.02, 0.722, 0.55, +0.2199, '建议'),
        },
        'C_放量1.2倍': {
            5: (0, None, None, None, None, '样本不足'),
            10: (0, None, None, None, None, '样本不足'),
            20: (0, None, None, None, None, '样本不足'),
        },
        'n_signals': {'基线_B1': 71, 'A_反弹力度2%': 6, 'B_RSI上穿40': 19, 'C_放量1.2倍': 0},
    },
    'hs300': {
        'name': '沪深300',
        'baseline': {
            5: (126, -0.35, 0.468, 0.86, -0.1475, '不建议'),
            10: (126, -0.56, 0.429, 0.95, -0.1709, '不建议'),
            20: (125, +0.00, 0.448, 1.23, +0.0007, '建议'),
        },
        'A_反弹力度2%': {
            5: (11, -0.49, 0.273, 2.10, -0.0737, '不建议'),
            10: (11, +0.53, 0.455, 1.45, +0.0775, '建议'),
            20: (11, +2.37, 0.545, 1.61, +0.2634, '建议'),
        },
        'B_RSI上穿40': {
            5: (27, -0.72, 0.481, 0.58, -0.4082, '不建议'),
            10: (27, -2.28, 0.407, 0.47, -0.8404, '不建议'),
            20: (26, +0.35, 0.538, 0.94, +0.0465, '建议'),
        },
        'C_放量1.2倍': {
            5: (0, None, None, None, None, '样本不足'),
            10: (0, None, None, None, None, '样本不足'),
            20: (0, None, None, None, None, '样本不足'),
        },
        'n_signals': {'基线_B1': 126, 'A_反弹力度2%': 11, 'B_RSI上穿40': 27, 'C_放量1.2倍': 0},
    },
    # 传媒 / 综合 / 钢铁 来自 18 报告（2026-07-08 回测）
    'sw_801760': {
        'name': '传媒',
        'baseline': {
            5: (69, 0.42, 0.623, 0.82, 0.1639, '建议'),
            10: (69, -0.42, 0.551, 0.65, -0.1403, '不建议'),
            20: (69, -0.45, 0.391, 1.32, -0.0699, '不建议'),
        },
        'A_反弹力度2%': {
            5: (8, 2.24, 0.750, 3.35, 0.6754, '样本不足'),
            10: (8, 2.05, 0.875, 0.94, 0.7420, '样本不足'),
            20: (8, 1.19, 0.500, 1.64, 0.1959, '样本不足'),
        },
        'B_RSI上穿40': {
            5: (19, 0.93, 0.632, 1.26, 0.3397, '建议'),
            10: (19, 0.59, 0.737, 0.57, 0.2766, '建议'),
            20: (19, 0.25, 0.316, 2.38, 0.0278, '建议'),
        },
        'C_放量1.2倍': {
            5: (1, 0.20, 1.000, None, None, '样本不足'),
            10: (1, 0.95, 1.000, None, None, '样本不足'),
            20: (1, 1.79, 1.000, None, None, '样本不足'),
        },
        'n_signals': {'基线_B1': 69, 'A_反弹力度2%': 8, 'B_RSI上穿40': 19, 'C_放量1.2倍': 1},
    },
    'sw_801230': {
        'name': '综合',
        'baseline': {
            5: (153, -0.14, 0.523, 0.84, -0.0461, '不建议'),
            10: (153, -0.67, 0.438, 0.99, -0.1307, '不建议'),
            20: (152, -0.05, 0.507, 0.96, -0.0078, '不建议'),
        },
        'A_反弹力度2%': {
            5: (20, -0.01, 0.500, 1.00, -0.0024, '不建议'),
            10: (20, -0.60, 0.500, 0.83, -0.1034, '不建议'),
            20: (19, 3.07, 0.632, 1.11, 0.3007, '建议'),
        },
        'B_RSI上穿40': {
            5: (40, 0.89, 0.625, 1.10, 0.2831, '建议'),
            10: (40, -0.16, 0.450, 1.15, -0.0289, '不建议'),
            20: (39, 0.05, 0.513, 0.96, 0.0070, '建议'),
        },
        'C_放量1.2倍': {
            5: (9, -0.18, 0.444, 1.12, -0.0495, '样本不足'),
            10: (9, -3.01, 0.556, 0.30, -0.9309, '样本不足'),
            20: (8, 0.50, 0.625, 0.65, 0.0465, '样本不足'),
        },
        'n_signals': {'基线_B1': 154, 'A_反弹力度2%': 21, 'B_RSI上穿40': 41, 'C_放量1.2倍': 9},
    },
    'sw_801040': {
        'name': '钢铁',
        'baseline': {
            5: (150, -0.20, 0.487, 0.93, -0.0667, '不建议'),
            10: (150, -0.56, 0.447, 0.97, -0.1222, '不建议'),
            20: (150, -0.21, 0.493, 0.96, -0.0338, '不建议'),
        },
        'A_反弹力度2%': {
            5: (20, -1.77, 0.450, 0.53, -0.5793, '不建议'),
            10: (20, -2.89, 0.350, 0.73, -0.5345, '不建议'),
            20: (20, -2.14, 0.400, 0.84, -0.3102, '不建议'),
        },
        'B_RSI上穿40': {
            5: (31, -0.57, 0.484, 0.81, -0.1523, '不建议'),
            10: (31, -0.56, 0.387, 1.27, -0.0957, '不建议'),
            20: (31, 0.80, 0.516, 1.20, 0.1142, '建议'),
        },
        'C_放量1.2倍': {
            5: (17, 1.40, 0.529, 1.71, 0.2550, '建议'),
            10: (17, 0.69, 0.529, 1.12, 0.1099, '建议'),
            20: (17, -1.11, 0.412, 1.09, -0.1275, '不建议'),
        },
        'n_signals': {'基线_B1': 151, 'A_反弹力度2%': 20, 'B_RSI上穿40': 31, 'C_放量1.2倍': 17},
    },
}

# 行业类型映射（用于 11+ 品类通用性分析）
INDUSTRY_TYPE = {
    'sw_801110': '消费白马(家电)',
    'sw_801200': '消费零售(商贸)',
    'sw_801730': '制造(电力设备)',
    'sw_801140': '制造(轻工)',
    'sw_801030': '周期(基础化工)',
    'sh': 'A股宽基(上证)',
    'csi1000': 'A股宽基(中证1000)',
    'hs300': 'A股宽基(沪深300)',
    'sw_801760': 'TMT(传媒)',
    'sw_801230': '综合(综合)',
    'sw_801040': '周期(钢铁)',
    # 第 20 批新增
    'csi500': 'A股宽基(中证500)',
    'cyb': 'A股宽基(创业板)',
    'sz_div': 'A股红利(深证红利)',
    'sw_801050': '周期(有色金属)',
    'sw_801120': '消费白马(食品饮料)',
    'sw_801150': '防御消费(医药生物)',
    # 第 21 批新增（剩余品类逐个优化）
    'kc50': 'A股宽基(科创50)',
    'sz': 'A股宽基(深证成指)',
    'sw_801130': '消费(纺织服饰)',
    'sw_801160': '防御(公用事业)',
    'sw_801170': '周期(交通运输)',
    'sw_801180': '周期(房地产)',
    'sw_801210': '消费(社会服务)',
    'sw_801770': 'TMT(通信)',
    'sw_801750': 'TMT(计算机)',
    'sw_801740': '制造(国防军工)',
    'sw_801970': '防御(环保)',
    'sw_801010': '防御(农林牧渔)',
    'sw_801080': 'TMT(电子)',
    'sw_801710': '周期(建筑材料)',
    'sw_801720': '周期(建筑装饰)',
    'sw_801780': '金融(银行)',
    'sw_801790': '金融(非银金融)',
    'sw_801890': '制造(机械设备)',
    'sw_801950': '周期(煤炭)',
    'sw_801960': '周期(石油石化)',
    'sw_801980': '消费(美容护理)',
    'csi_div': 'A股红利(中证红利)',
    'div_lowvol': 'A股红利(红利低波)',
    'hsi': '港股(恒生指数)',
    'hstech': '港股(恒生科技)',
    'hscei': '港股(恒生国企)',
    'us_dji': '美股(道琼斯)',
    'us_ixic': '美股(纳斯达克)',
    'us_spx': '美股(标普500)',
    'us_ndx': '美股(纳斯达克100)',
}

# ===================== 指标复刻（与 signals.py 一致）=====================

def rsi(close, period=14):
    """RSI(14) EWM α=1/period adjust=False（复刻 signals.py `_rsi`）。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def bollinger(close, window=20, n_std=2.0):
    """BB(20, 2.0) std ddof=0（复刻 signals.py `_bollinger`）。返回 (bu, mid, bl)。"""
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    return mid + n_std * sd, mid, mid - n_std * sd


# ===================== 买点方案 =====================

def buy_aux_baseline(close, amount=None, buy_set=None):
    """基线 B1：BB 下轨回归（close_prev<bl_prev 且 close>bl）。"""
    if len(close) < 30:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    mask = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    return _dedup(mask, buy_set)


def buy_aux_scheme_a(close, amount=None, buy_set=None, rebound_pct=0.02):
    """方案 A：反弹力度确认（close > bl × (1+rebound_pct)）。"""
    if len(close) < 30:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    thresh = bl * (1 + rebound_pct)
    mask = ((close.shift(1) < bl.shift(1)) & (close > thresh)).fillna(False)
    return _dedup(mask, buy_set)


def buy_aux_scheme_b(close, amount=None, buy_set=None, rsi_thresh=40):
    """方案 B：RSI 动量确认（BB下轨回归 + RSI 上穿 rsi_thresh）。"""
    if len(close) < 30:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    r = rsi(close, 14)
    rp = r.shift(1)
    bb_revert = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    rsi_cross = ((rp <= rsi_thresh) & (r > rsi_thresh)).fillna(False)
    mask = bb_revert & rsi_cross
    return _dedup(mask, buy_set)


def buy_aux_scheme_c(close, amount=None, buy_set=None, vol_mult=1.2, vol_window=5):
    """方案 C：放量确认（BB下轨回归 + amount > 5日均量 × 1.2）。"""
    if len(close) < 30 or amount is None:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    bb_revert = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    vol_ma = amount.rolling(vol_window).mean()
    vol_surge = (amount > vol_ma * vol_mult).fillna(False)
    mask = bb_revert & vol_surge
    return _dedup(mask, buy_set)


def _dedup(buy_aux_mask, buy_set):
    """C1 与 buy_aux 同日触发时去重：保留 C1。"""
    if buy_set is None:
        return buy_aux_mask
    out = buy_aux_mask.copy()
    for d in buy_set:
        if d in out.index:
            out.at[d] = False
    return out


# ===================== C1 主买（用于去重）=====================

def compute_c1_buy(close):
    """C1 主买：RSI(14) 上穿 30。返回 buy_set（date set）。"""
    if len(close) < 30:
        return set()
    r = rsi(close, 14)
    rp = r.shift(1)
    buy = ((rp <= 30) & (r > 30)).fillna(False)
    return set(buy[buy].index)


# ===================== 数据加载 =====================

def load_index_ohlcv(iid):
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, amount FROM index_daily "
        "WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    df = df.set_index('date').astype(float)
    return df


# ===================== 回测工具 =====================

def forward_returns(close, sig_mask, horizon):
    arr = close.values
    n = len(arr)
    sig_idx = np.where(sig_mask.values)[0]
    out = []
    for pos in sig_idx:
        if pos + horizon < n:
            out.append((arr[pos + horizon] - arr[pos]) / arr[pos] * 100.0)
    return out


def stats_block(returns):
    if not returns:
        return (0, float('nan'), float('nan'), float('nan'), None)
    arr = np.array(returns, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    n = len(arr)
    wr = len(wins) / n
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = (avg_win / avg_loss) if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    f = None
    if not np.isnan(pl) and pl > 0:
        f = (pl * wr - (1 - wr)) / pl
    return (n, float(arr.mean()), float(wr), float(pl), f)


def kelly_class(n, f):
    if n < KELLY_INSUF_N:
        return 'insuf', '样本不足'
    if f is None or f <= 0:
        return 'not_rec', '不建议'
    return 'rec', '建议'


def fmt_pct(x, nd=1):
    return f"{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_pl(x):
    return f"{x:.2f}" if not np.isnan(x) else "-"


def fmt_mean(x, nd=2):
    sign = "+" if (not np.isnan(x) and x > 0) else ""
    return f"{sign}{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_f(x):
    if x is None:
        return "-"
    return f"{x*100:.2f}%"


def consistency_str(fs):
    f_signs = [(1 if (x is not None and x > 0) else 0) for x in fs]
    if all(s == 1 for s in f_signs):
        return "三 horizon 一致转正（f>0）"
    if all(s == 0 for s in f_signs):
        return "三 horizon 一致不建议（f≤0）"
    return "三 horizon 不一致（部分转正部分不建议）"


def consistency_short(fs):
    f_signs = [(1 if (x is not None and x > 0) else 0) for x in fs]
    if all(s == 1 for s in f_signs):
        return "一致转正"
    if all(s == 0 for s in f_signs):
        return "一致不建议"
    return "不一致"


SCHEMES = [
    ('基线_B1', buy_aux_baseline, {}),
    ('A_反弹力度2%', buy_aux_scheme_a, {'rebound_pct': 0.02}),
    ('B_RSI上穿40', buy_aux_scheme_b, {'rsi_thresh': 40}),
    ('C_放量1.2倍', buy_aux_scheme_c, {'vol_mult': 1.2, 'vol_window': 5}),
]

# 方案元信息（用于报告写作）
SCHEME_META = {
    'A_反弹力度2%': {
        'logic': '**反弹力度确认**：BB 下轨回归 + close 收回下轨之上 2%（`close > bl × 1.02`）。'
                 '现状是 close>bl 即触发（barely crossed 也算），改为要求 close 高于下轨 2%。',
        'why': '现状 buy_aux 的核心问题是「barely crossed」型假信号——close 刚刚高出下轨 0.01% 就触发，'
               '这种反弹没有力度，往往是下跌中继的短暂停顿（dead cat bounce 的前半段）。'
               '要求 close 高于下轨 2%，确保反弹有实质买盘力度，过滤掉「刚探头就缩回」的假突破。'
               '2% 是 A 股指数日内常见波动幅度，不算苛刻。',
        'expect': '信号数减少（更严格）、胜率提升（留下的反弹更有力度）；但减少幅度未知，'
               '若过严可能样本不足。',
    },
    'B_RSI上穿40': {
        'logic': '**RSI 动量确认**：BB 下轨回归 + RSI(14) 上穿 40（`rsi_prev ≤ 40 & rsi > 40`）。'
                 '价格反弹 + 动量转升双重确认。RSI 上穿 40（而非 30）避免与 C1 完全重叠——'
                 'C1 是 RSI 上穿 30，去重后 buy_aux_B 只在 RSI 30-40 区间上穿 40 时触发'
                 '（即 C1 未触发的轻度超卖反弹子集）。',
        'why': 'BB 下轨回归只看价格穿越（一维），不确认动量是否真转升。'
               'RSI 上穿 40 = 动量已从超卖区开始向上突破（虽未到 C1 的 30 阈值，但已过 40），'
               '是「价格反弹 + 动量转升」双维确认，与 sell 的 MACD 死叉确认（D1+S1 + DIF<DEA）'
               '对称——都是给一维价格信号加正交的动量维确认。'
               'RSI 40 是业界常用的超卖/正常分界（30=深度超卖，40=轻度超卖，50=中性），'
               '非调参。此方案与 C1 互补不冲突（C1 抓深度超卖 RSI<30，B 抓轻度超卖 RSI 30-40）。',
        'expect': '信号数减少（要求 RSI 穿越额外条件）、胜率可能提升（动量确认）；'
               '但 RSI 30-40 区间的反弹力度本就弱于 RSI<30，提升幅度可能有限。',
    },
    'C_放量1.2倍': {
        'logic': '**放量确认**：BB 下轨回归 + 当日成交金额 > 5 日均额 × 1.2（`amount > amount.rolling(5).mean() × 1.2`）。'
                 '用 amount（成交金额）作 volume 代理——比 volume（股数）更能反映资金进场规模。',
        'why': 'BB 下轨回归是价格信号，不反映成交量。缩量反弹往往是「没人愿意接」的死猫 bounce，'
               '放量反弹才是「有资金主动进场接盘」的真反弹。量价关系是技术分析最经典的正交维度'
               '（道氏理论三大假设之一：趋势需成交量确认）。1.2 倍是温和放量阈值（业界常用 1.5 倍 '
               '激进，1.2 倍温和），5 日均额是短期资金基准。',
        'expect': '信号数减少（要求放量）、胜率提升（资金进场确认）；但行业指数的放量与价格反弹'
               '相关性可能不如个股强（指数是组合，资金分散），效果待数据。',
    },
}


def run_one_category(sid, sid_name):
    """跑单个品类的全部方案 × 全 horizon。返回 (results, n_signals_map, df_meta)。"""
    df = load_index_ohlcv(sid)
    if df is None:
        return None, None, None
    close = df['close']
    amount = df['amount'] if 'amount' in df.columns else None
    buy_set = compute_c1_buy(close)

    results = {sn: {} for sn, _, _ in SCHEMES}
    n_signals_map = {}
    for sn, func, kwargs in SCHEMES:
        mask = func(close, amount=amount, buy_set=buy_set, **kwargs)
        n_signals = int(mask.sum())
        n_signals_map[sn] = n_signals
        for h in HORIZONS:
            rets = forward_returns(close, mask, h)
            n, m, wr, pl, f = stats_block(rets)
            cls, lbl = kelly_class(n, f)
            results[sn][h] = (n, m, wr, pl, f, cls, lbl)

    df_meta = {
        'rows': len(close),
        'date_start': close.index[0].date(),
        'date_end': close.index[-1].date(),
        'amount_min': float(amount.min()) if amount is not None else None,
        'amount_max': float(amount.max()) if amount is not None else None,
        'amount_null': int(amount.isna().sum()) if amount is not None else None,
        'c1_buy_n': len(buy_set),
    }
    return results, n_signals_map, df_meta


# ===================== 报告生成（每品类一节）=====================

def render_category_section(sid, sid_name, results, n_signals_map, meta, baseline_target=None):
    """渲染单个品类的报告章节。baseline_target 是 signal_stats.json 里的基线，用于核对。"""
    L = []
    A = L.append
    A(f"## 品类 {sid} {sid_NAME_map[sid]}\n")
    A(f"- 数据源：data/sentiment.db index_daily（{meta['rows']} 行，{meta['date_start']} ~ {meta['date_end']}）")
    A(f"- horizon：5d / 10d / 20d 三 horizon（10d 主指标与前端 tips 一致，5d/20d 验证一致性）")
    A(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 signals.py `_rsi`）")
    A(f"- BB 算法：window=20, n_std=2.0, std ddof=0（复刻 signals.py `_bollinger`）")
    A(f"- 凯利公式：f* = (b·p - (1-p))/b，p=胜率 b=盈亏比；f>0=建议，f≤0=不建议，n<10=样本不足")
    A(f"- 买点胜率=收益>0占比（信号后 N 日上涨才算对）；盈亏比=平均盈利(涨)/平均亏损(跌)")
    A(f"- 去重：C1 主买（RSI 上穿 30）与 buy_aux 同日触发时保留 C1，不重复发 buy_aux（与 signals.py 一致）")
    A(f"- 3 个改进方案：A(反弹力度2%) / B(RSI上穿40) / C(放量1.2倍)（与家电/商贸同方案，横向可比）")
    A(f"- C1 主买信号数：{meta['c1_buy_n']}（用于去重）")
    if meta['amount_min'] is not None:
        A(f"- amount 范围 {meta['amount_min']:.2f} ~ {meta['amount_max']:.2f}，null {meta['amount_null']}")
    A("")

    # 基线复现核对
    if baseline_target is not None:
        A("### 基线复现核对（vs signal_stats.json）\n")
        A("| horizon | 本脚本 n | stats.json n | 本脚本 胜率 | stats.json 胜率 | 本脚本 盈亏比 | stats.json 盈亏比 | 一致 |")
        A("|---|---:|---:|---:|---:|---:|---:|---|")
        for h in HORIZONS:
            n, m, wr, pl, f, cls, lbl = results['基线_B1'][h]
            # 兼容 int key（{5:...}）和 str key（{"5d":...}）
            tgt = baseline_target.get(h) or baseline_target.get(f"{h}d", {})
            tgt_n = tgt.get('n')
            tgt_wr = tgt.get('win_rate')
            tgt_pl = tgt.get('pl')
            ok = (n == tgt_n and abs(wr - tgt_wr) < 1e-3 and abs(pl - tgt_pl) < 1e-3) if tgt_n is not None else False
            A(f"| {h}d{' **主**' if h==PRIMARY_HORIZON else ''} | {n} | {tgt_n} | "
              f"{fmt_pct(wr*100)} | {fmt_pct(tgt_wr*100) if tgt_wr is not None else '-'} | "
              f"{fmt_pl(pl)} | {fmt_pl(tgt_pl) if tgt_pl is not None else '-'} | "
              f"{'✅' if ok else '❌'} |")
        A("")
        A("> 基线复现应与 signal_stats.json 吻合（f/胜率/盈亏比/n）。如不一致说明脚本逻辑漂移，需排查。\n")

    # 1. 基线
    A(f"### {sid} 基线（当前 B1 buy_aux）凯利状态\n")
    A("当前 buy_aux 逻辑：BB 下轨回归——前一日 close<下轨 且当日 close>下轨（从超卖区反弹回下轨之上）。")
    base_n10 = results['基线_B1'][10][0]
    base_wr10 = results['基线_B1'][10][2]
    base_pl10 = results['基线_B1'][10][3]
    base_f10 = results['基线_B1'][10][4]
    base_m10 = results['基线_B1'][10][1]
    A(f"- **建议（f>0）**：否（f={fmt_f(base_f10)}，不建议）")
    A(f"- 胜率 {fmt_pct(base_wr10*100)} / 盈亏比 {fmt_pl(base_pl10)} / 样本 n={base_n10} / 均值 {fmt_mean(base_m10)} / 凯利 f={fmt_f(base_f10)}")
    A(f"- 信号总数（全史事件数）：{n_signals_map['基线_B1']}")
    A("")
    A("#### 基线三 horizon 一致性\n")
    A("| horizon | n | 胜率 | 盈亏比 | 均值 | 凯利f | 凯利 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for h in HORIZONS:
        n, m, wr, pl, f, cls, lbl = results['基线_B1'][h]
        primary = " **主**" if h == PRIMARY_HORIZON else ""
        A(f"| {h}d{primary} | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} |")
    A("")
    base_fs = [results['基线_B1'][h][4] for h in HORIZONS]
    A(f"> 基线 buy_aux 三 horizon {consistency_str(base_fs)}。")
    if base_wr10 < 0.5 and base_pl10 < 1.0 and base_m10 < 0:
        A(f"> 10d 主 horizon 胜率 {fmt_pct(base_wr10*100)} < 50%，盈亏比 {fmt_pl(base_pl10)} < 1，均值 {fmt_mean(base_m10)} < 0——三维全负，确认是「真不建议」而非参数偶发。")
    A("")

    # 2. 各方案
    for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
        r = results[sn]
        letter = ['A', 'B', 'C'][['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍'].index(sn)]
        A(f"### {sid} 方案 {letter}（{sn}）\n")
        A(f"**逻辑**：{SCHEME_META[sn]['logic']}\n")
        A(f"**金融依据**：{SCHEME_META[sn]['why']}\n")
        A(f"**预期**：{SCHEME_META[sn]['expect']}\n")
        A("#### 全量回测结果（三 horizon）\n")
        A("| horizon | n | 胜率 | 盈亏比 | 均值 | 凯利f | 凯利 | vs基线f |")
        A("|---|---:|---:|---:|---:|---:|---|---|")
        for h in HORIZONS:
            n, m, wr, pl, f, cls, lbl = r[h]
            base_f_h = results['基线_B1'][h][4]
            if f is not None and base_f_h is not None:
                delta = f - base_f_h
                delta_str = f"{delta*100:+.2f}pp"
            else:
                delta_str = "-"
            primary = " **主**" if h == PRIMARY_HORIZON else ""
            warn = f" ⚠️n<{SAMPLE_WARN_N}" if n < SAMPLE_WARN_N else ""
            A(f"| {h}d{primary} | {n}{warn} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} | {delta_str} |")
        A("")
        n10, m10, wr10, pl10, f10, cls10, lbl10 = r[10]
        n_base = results['基线_B1'][10][0]
        sig_delta = n_signals_map[sn] - n_signals_map['基线_B1']
        sig_pct = sig_delta / n_signals_map['基线_B1'] * 100 if n_signals_map['基线_B1'] else 0
        f_delta_pp = (f10 - base_f10) * 100 if (f10 is not None and base_f10 is not None) else 0
        A(f"**10d 主 horizon 摘要**：胜率 {fmt_pct(wr10*100)}（基线 {fmt_pct(base_wr10*100)}，"
          f"{(wr10-base_wr10)*100:+.1f}pp）/ 盈亏比 {fmt_pl(pl10)}（基线 {fmt_pl(base_pl10)}）/ "
          f"凯利 f={fmt_f(f10)}（基线 {fmt_f(base_f10)}，{f_delta_pp:+.2f}pp）/ "
          f"样本 n={n10}（基线 {n_base}）/ 均值 {fmt_mean(m10)}")
        A(f"**信号数**：{n_signals_map[sn]}（基线 {n_signals_map['基线_B1']}，{sig_delta:+d}，{sig_pct:+.1f}%）")
        fs = [r[h][4] for h in HORIZONS]
        A(f"**三 horizon 一致性**：{consistency_str(fs)}")
        if n10 < SAMPLE_WARN_N:
            A(f"**⚠️ 样本不足警示**：10d n={n10} < {SAMPLE_WARN_N}，结论仅供参考，可能过拟合。")
        A("")

    # 3. 方案对比表
    A(f"### {sid} 方案对比（一栏一方案）\n")
    A("| 指标 | 基线 B1 | A 反弹力度2% | B RSI上穿40 | C 放量1.2倍 |")
    A("|---|---:|---:|---:|---:|")
    for label, key in [('10d 胜率', 'wr'), ('10d 盈亏比', 'pl'), ('10d 均值', 'mean'),
                       ('10d 凯利f', 'f'), ('10d 凯利状态', 'lbl')]:
        cells = []
        for sn, _, _ in SCHEMES:
            n, m, wr, pl, f, cls, lbl = results[sn][10]
            if key == 'wr':
                cells.append(fmt_pct(wr*100))
            elif key == 'pl':
                cells.append(fmt_pl(pl))
            elif key == 'mean':
                cells.append(fmt_mean(m))
            elif key == 'f':
                cells.append(fmt_f(f))
            elif key == 'lbl':
                cells.append(lbl)
        A(f"| {label} | " + " | ".join(cells) + " |")
    A(f"| 10d 样本 n | {results['基线_B1'][10][0]} | {results['A_反弹力度2%'][10][0]} | "
      f"{results['B_RSI上穿40'][10][0]} | {results['C_放量1.2倍'][10][0]} |")
    sig_cells = [str(n_signals_map[sn]) for sn, _, _ in SCHEMES]
    A(f"| 全史信号数 | " + " | ".join(sig_cells) + " |")
    sig_delta_cells = []
    for sn, _, _ in SCHEMES:
        d = n_signals_map[sn] - n_signals_map['基线_B1']
        pct = d / n_signals_map['基线_B1'] * 100 if n_signals_map['基线_B1'] else 0
        sig_delta_cells.append(f"{d:+d} ({pct:+.1f}%)")
    A(f"| 信号数变化（vs基线） | — | " + " | ".join(sig_delta_cells[1:]) + " |")
    f_delta_cells = []
    for sn, _, _ in SCHEMES:
        f = results[sn][10][4]
        if f is not None and base_f10 is not None:
            f_delta_cells.append(f"{(f-base_f10)*100:+.2f}pp")
        else:
            f_delta_cells.append("-")
    A(f"| 10d f 改善（vs基线） | — | " + " | ".join(f_delta_cells[1:]) + " |")
    wr_delta_cells = []
    for sn, _, _ in SCHEMES:
        wr = results[sn][10][2]
        wr_delta_cells.append(f"{(wr-base_wr10)*100:+.1f}pp")
    A(f"| 10d 胜率改善（vs基线） | — | " + " | ".join(wr_delta_cells[1:]) + " |")
    zhuanzheng_cells = []
    for sn, _, _ in SCHEMES:
        f = results[sn][10][4]
        zhuanzheng_cells.append("✅ 转正" if (f is not None and f > 0) else "❌ 未转正")
    A(f"| 是否转正（f>0） | " + " | ".join(zhuanzheng_cells) + " |")
    consistency_cells = [consistency_short([results[sn][h][4] for h in HORIZONS]) for sn, _, _ in SCHEMES]
    A(f"| 三 horizon 一致性 | " + " | ".join(consistency_cells) + " |")
    A("")

    # 4. 推荐
    A(f"### {sid} 推荐方案\n")
    best_sn = max(['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍'],
                  key=lambda sn: results[sn][10][4] if results[sn][10][4] is not None else -999)
    best_f = results[best_sn][10][4]
    best_n10 = results[best_sn][10][0]
    if best_f is not None and best_f > 0:
        A(f"基于数据，**方案 {best_sn.split('_')[0]}（{best_sn}）** 10d 凯利 f 转正（{fmt_f(best_f)}，"
          f"基线 {fmt_f(base_f10)}，改善 {(best_f-base_f10)*100:+.2f}pp），样本 n={best_n10}。")
    else:
        A(f"基于数据，**方案 {best_sn.split('_')[0]}（{best_sn}）** 10d 凯利 f 最高（{fmt_f(best_f)}，"
          f"基线 {fmt_f(base_f10)}，改善 {(best_f-base_f10)*100:+.2f}pp），但未达凯利建议。")
    A("")
    for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
        f10 = results[sn][10][4]
        n10 = results[sn][10][0]
        wr10 = results[sn][10][2]
        pl10 = results[sn][10][3]
        if f10 is not None and f10 > 0:
            A(f"- **方案 {sn.split('_')[0]}（{sn}）**：✅ **转正**，10d f={fmt_f(f10)}，"
              f"胜率 {fmt_pct(wr10*100)} / 盈亏比 {fmt_pl(pl10)} / n={n10}")
        else:
            A(f"- **方案 {sn.split('_')[0]}（{sn}）**：❌ 未转正，10d f={fmt_f(f10)}，"
              f"胜率 {fmt_pct(wr10*100)}（vs基线 {(wr10-base_wr10)*100:+.1f}pp）/ n={n10}")
    A("")
    A("**最终方案由用户选定**（以下诚实结论 + 横向对比辅助判断）。\n")

    # 5. 诚实结论
    A(f"### {sid} 诚实结论\n")
    turned_positive = [sn for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']
                       if results[sn][10][4] is not None and results[sn][10][4] > 0]
    A(f"#### 转正情况\n")
    if turned_positive:
        A(f"**{len(turned_positive)} 个方案让 {sid} buy_aux 凯利转正（f>0）**：")
        for sn in turned_positive:
            n10, m10, wr10, pl10, f10, cls10, lbl10 = results[sn][10]
            base_n = results['基线_B1'][10][0]
            base_wr = results['基线_B1'][10][2]
            A(f"- {sn}：f={fmt_f(f10)}，胜率 {fmt_pct(wr10*100)}（{(wr10-base_wr)*100:+.1f}pp），"
              f"盈亏比 {fmt_pl(pl10)}，n={n10}（vs基线 {base_n}）")
        A(f"\n**推荐 {best_sn}**（10d f 最高，三 horizon 一致性见上表）。")
    else:
        A(f"**0 个方案让 {sid} buy_aux 凯利转正（f>0）**——所有方案 10d f 仍 ≤0。")
        A(f"退而求其次看胜率提升：")
        for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
            n10, m10, wr10, pl10, f10, cls10, lbl10 = results[sn][10]
            base_wr = results['基线_B1'][10][2]
            A(f"- {sn}：胜率 {fmt_pct(wr10*100)}（{(wr10-base_wr)*100:+.1f}pp），n={n10}，"
              f"f={fmt_f(f10)}（未达凯利建议，但胜率{'提升' if wr10>base_wr else '未提升'}）")
        A(f"\n**无方案转正**——{sid} buy_aux 优化空间有限，建议维持现状或考虑 skip 该品类的 buy_aux。")
    A("")

    A(f"#### 过拟合警示\n")
    A(f"- **参数选择性**：试了 3 个方案（A 反弹 2% / B RSI 40 / C 放量 1.2 倍），"
      f"每个方案的参数（2% / 40 / 1.2 倍）都是业界常用值而非历史调参，但仍有选择性偏差风险——"
      f"可能存在其他参数组合效果更好或更差。本回测的结论是「这 3 个业界标准方案的表现」，"
      f"不等于「buy_aux 最优方案」。")
    A(f"- **样本数**：基线 n={base_n10}，各方案 n 见上表。若某方案 n<30（样本不足警示），"
      f"其结论仅供参考，可能过拟合小样本。")
    A(f"- **三 horizon 一致性**：10d 是主指标，5d/20d 验证。若某方案仅 10d 转正而 5d/20d 不转正，"
      f"可能是单 horizon 偶发，稳健性存疑。一致转正（三 horizon 都 f>0）才稳健。")
    A(f"- **品类特异性**：{sid} 是单个品类回测，方案在不同品类的表现可能差异大，"
      f"buy_aux 优化的共性方向需在多品类汇总后判断（见横向对比节）。")
    A("")

    A(f"#### 总判断\n")
    if turned_positive:
        best_fs = [results[best_sn][h][4] for h in HORIZONS]
        all_positive = all(x is not None and x > 0 for x in best_fs)
        A(f"**方案 {best_sn} 让 {sid} buy_aux 凯利转正**（10d f={fmt_f(best_f)}，n={best_n10}）。")
        if all_positive:
            A(f"三 horizon 一致转正（5d/10d/20d 均 f>0），稳健性高，非单 horizon 偶发。")
        else:
            A(f"⚠️ 三 horizon 不一致（非全部 f>0），10d 转正可能是单 horizon 偶发，稳健性存疑。")
        A(f"**建议落地方案 {best_sn}**（如用户认可）：")
        A(f"- `app/compute/signals.py` 的 buy_aux 判定加方案对应条件（参考 sw_801110 的 `buy_aux_filter` 配置化）")
        A(f"- 重算 signal_daily + signal_stats.json")
        A(f"- 同步 REQUIREMENTS §7.4 变更历史 + 前端 ruleBar 文案")
        A(f"")
        A(f"**诚实提醒**：转正不等于「稳赚」。凯利 f>0 只意味着「正期望」，f 值通常较小"
          f"（个位数百分比），对应建议仓位很轻。buy_aux 仍是辅买点，置信度低于 C1 主买，"
          f"适合小仓位试探或观察确认，不可替代 C1 主买。")
    else:
        best_wr_sn = max(['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍'],
                         key=lambda sn: results[sn][10][2])
        best_wr = results[best_wr_sn][10][2]
        A(f"**所有 3 个方案均无法让 {sid} buy_aux 凯利转正**。")
        A(f"胜率提升最多的是 {best_wr_sn}（{fmt_pct(best_wr*100)}，{(best_wr-base_wr10)*100:+.1f}pp），"
          f"但仍未达凯利建议。")
        A(f"")
        A(f"**建议**：")
        A(f"- 若用户接受「退而求其次提高胜率」（不强求凯利转正），可选 {best_wr_sn}")
        A(f"- 若用户坚持凯利转正才落地，建议 **维持现状或 skip {sid} 的 buy_aux**")
        A(f"  （即该品类不发 buy_aux 信号，避免误导用户）")
        A(f"")
        A(f"**根本原因诊断**：{sid} 指数在 BB 下轨回归日的反弹力度结构性偏弱，"
          f"可能是行业特性，非参数可调。可考虑换信号逻辑（如改用 RSI 双底、成交量底部背离等），"
          f"但超出本回测范围。")
    A("")

    # 6. 附录
    A(f"### {sid} 附录：各方案三 horizon 完整数据\n")
    for sn, _, _ in SCHEMES:
        A(f"#### {sn}\n")
        A("| horizon | n | 胜率 | 盈亏比 | 均值 | 凯利f | 凯利 | 信号数 |")
        A("|---|---:|---:|---:|---:|---:|---|---:|")
        for h in HORIZONS:
            n, m, wr, pl, f, cls, lbl = results[sn][h]
            primary = " **主**" if h == PRIMARY_HORIZON else ""
            warn = f" ⚠️" if n < SAMPLE_WARN_N else ""
            A(f"| {h}d{primary} | {n}{warn} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} | {n_signals_map[sn]} |")
        A("")

    return L


# ===================== 全品类汇总表 =====================

def _norm(t):
    """归一化元组：6 元组 (n,m,wr,pl,f,lbl) → 7 元组 (n,m,wr,pl,f,cls,lbl)。
    PRIOR_CATEGORIES 用 6 元组（无 cls），本次回测用 7 元组（有 cls），统一成 7 元组。"""
    if len(t) == 7:
        return t
    n, m, wr, pl, f, lbl = t
    cls = 'rec' if lbl == '建议' else ('not_rec' if lbl == '不建议' else 'insuf')
    return (n, m, wr, pl, f, cls, lbl)


def render_summary(all_cat_results):
    """三品类横向对比 + 与家电/商贸汇总 + 方案B通用性结论。"""
    L = []
    A = L.append

    # 收集所有 5 品类 × 4 方案 × 3 horizon 的数据（统一 7 元组）
    all5 = {}
    for sid, info in PRIOR_CATEGORIES.items():
        all5[sid] = {'name': info['name'], 'industry': INDUSTRY_TYPE.get(sid, '?')}
        all5[sid]['baseline'] = {h: _norm(t) for h, t in info['baseline'].items()}
        for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
            all5[sid][sn] = {h: _norm(t) for h, t in info[sn].items()}
        all5[sid]['n_signals'] = info['n_signals']
    for sid, (results, n_signals_map, meta) in all_cat_results.items():
        all5[sid] = {'name': sid_NAME_map[sid], 'industry': INDUSTRY_TYPE.get(sid, '?')}
        all5[sid]['baseline'] = {h: results['基线_B1'][h] for h in HORIZONS}
        for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
            all5[sid][sn] = {h: results[sn][h] for h in HORIZONS}
        all5[sid]['n_signals'] = n_signals_map

    # ---- 三品类横向对比 ----
    live_sids = list(all_cat_results.keys())
    A(f"## 本次回测品类横向对比（{len(live_sids)} 品类）\n")
    A(f"对本次回测的 {len(live_sids)} 个品类（{' / '.join(sid_NAME_map.get(s, s) for s in live_sids)}）做横向对比，判断方案A/B 在各品类的 f 变化。\n")

    A("### 本次回测品类基线对比\n")
    A("| 品类 | 行业类型 | 数据行 | 10d 胜率 | 10d 盈亏比 | 10d 均值 | 10d 凯利f | 10d 凯利 | 10d n | 全史信号 |")
    A("|---|---|---:|---:|---:|---:|---:|---|---:|---:|")
    for sid in live_sids:
        info = all5[sid]
        n, m, wr, pl, f, cls, lbl = info['baseline'][10]
        meta = all_cat_results[sid][2]
        A(f"| {sid} {info['name']} | {info['industry']} | {meta['rows']} | "
          f"{fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} | {n} | {info['n_signals']['基线_B1']} |")
    A("")

    A(f"### 本次回测品类 × A/B/C 方案 10d f 矩阵\n")
    A("| 品类 | 基线 f | A f | A 转正 | B f | B 转正 | C f | C 转正 | 最优方案 | 最优 f |")
    A("|---|---:|---:|---|---:|---|---:|---|---|---:|")
    for sid in live_sids:
        info = all5[sid]
        base_f = info['baseline'][10][4]
        a_n, a_m, a_wr, a_pl, a_f, a_cls, a_lbl = info['A_反弹力度2%'][10]
        b_n, b_m, b_wr, b_pl, b_f, b_cls, b_lbl = info['B_RSI上穿40'][10]
        c_n, c_m, c_wr, c_pl, c_f, c_cls, c_lbl = info['C_放量1.2倍'][10]
        # 最优：f 最大且 n>=10
        candidates = []
        if a_f is not None and a_n >= KELLY_INSUF_N:
            candidates.append(('A', a_f))
        if b_f is not None and b_n >= KELLY_INSUF_N:
            candidates.append(('B', b_f))
        if c_f is not None and c_n >= KELLY_INSUF_N:
            candidates.append(('C', c_f))
        if candidates:
            best_letter, best_f_val = max(candidates, key=lambda x: x[1])
        else:
            best_letter, best_f_val = '?', None
        A(f"| {sid} {info['name']} | {fmt_f(base_f)} | {fmt_f(a_f)} | "
          f"{'✅' if (a_f is not None and a_f>0 and a_n>=KELLY_INSUF_N) else '❌'} | "
          f"{fmt_f(b_f)} | {'✅' if (b_f is not None and b_f>0 and b_n>=KELLY_INSUF_N) else '❌'} | "
          f"{fmt_f(c_f)} | {'✅' if (c_f is not None and c_f>0 and c_n>=KELLY_INSUF_N) else '❌'} | "
          f"{best_letter} | {fmt_f(best_f_val)} |")
    A("")

    A(f"### 本次回测品类 × 方案B（RSI上穿40）三 horizon 一致性\n")
    A("| 品类 | B 5d f | B 10d f | B 20d f | B 10d n | B 全史信号 | 三 horizon 一致性 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for sid in live_sids:
        info = all5[sid]
        b5 = info['B_RSI上穿40'][5]
        b10 = info['B_RSI上穿40'][10]
        b20 = info['B_RSI上穿40'][20]
        fs = [b5[4], b10[4], b20[4]]
        A(f"| {sid} {info['name']} | {fmt_f(b5[4])} | {fmt_f(b10[4])} | {fmt_f(b20[4])} | "
          f"{b10[0]} | {info['n_signals']['B_RSI上穿40']} | {consistency_short(fs)} |")
    A("")

    # ---- 8 品类汇总（前 8 已测品类 + 本次 live 品类）----
    all_prior_sids = list(PRIOR_CATEGORIES.keys())
    all_8_sids = all_prior_sids + live_sids  # 8 prior + N live = 8+N
    n_total_cats = len(all_8_sids)
    prior_names = ' / '.join(f"{sid_NAME_map.get(s, s)}" for s in all_prior_sids)
    live_names = ' / '.join(f"{sid_NAME_map.get(s, s)}" for s in live_sids)
    A(f"## {n_total_cats} 品类汇总（前 {len(all_prior_sids)} 品类：{prior_names} + 本次 {len(live_sids)} 品类：{live_names}）\n")
    A(f"把已完成的 {n_total_cats} 个品类的 buy_aux 优化结果汇总，判断方案A/B 适用于哪类行业/宽基。\n")

    A(f"### {n_total_cats} 品类 × A/B/C 方案 10d f 全表\n")
    A("| 品类 | 行业类型 | 基线 f | A f | B f | C f | B 转正 | 三 horizon 一致性(B) |")
    A("|---|---|---:|---:|---:|---:|---|---|")
    order = all_8_sids
    for sid in order:
        info = all5[sid]
        base_f = info['baseline'][10][4]
        a_f = info['A_反弹力度2%'][10][4]
        b_f = info['B_RSI上穿40'][10][4]
        c_f = info['C_放量1.2倍'][10][4]
        b_fs = [info['B_RSI上穿40'][h][4] for h in HORIZONS]
        b_turn = '✅ 转正' if (b_f is not None and b_f > 0 and info['B_RSI上穿40'][10][0] >= KELLY_INSUF_N) else '❌ 未转正'
        A(f"| {sid} {info['name']} | {info['industry']} | {fmt_f(base_f)} | {fmt_f(a_f)} | "
          f"{fmt_f(b_f)} | {fmt_f(c_f)} | {b_turn} | {consistency_short(b_fs)} |")
    A("")

    # 方案B 全品类细分表
    A(f"### 方案B（RSI上穿40）{n_total_cats} 品类细分\n")
    A("| 品类 | 行业类型 | B 5d f | B 10d f | B 20d f | B 10d 胜率 | B 10d 盈亏比 | B 10d n | B 全史信号 | B 转正 |")
    A("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    b_turn_list = []
    for sid in order:
        info = all5[sid]
        b5 = info['B_RSI上穿40'][5]
        b10 = info['B_RSI上穿40'][10]
        b20 = info['B_RSI上穿40'][20]
        b_turn = (b10[4] is not None and b10[4] > 0 and b10[0] >= KELLY_INSUF_N)
        b_turn_list.append((sid, info['name'], info['industry'], b_turn, b10[4]))
        A(f"| {sid} {info['name']} | {info['industry']} | {fmt_f(b5[4])} | {fmt_f(b10[4])} | "
          f"{fmt_f(b20[4])} | {fmt_pct(b10[2]*100)} | {fmt_pl(b10[3])} | {b10[0]} | "
          f"{info['n_signals']['B_RSI上穿40']} | {'✅' if b_turn else '❌'} |")
    A("")

    # 通用性结论
    A(f"### 方案B 通用性结论（{n_total_cats} 品类）\n")
    turned = [(sid, name, ind, f) for (sid, name, ind, t, f) in b_turn_list if t]
    not_turned = [(sid, name, ind, f) for (sid, name, ind, t, f) in b_turn_list if not t]
    A(f"{n_total_cats} 品类中方案B（RSI上穿40）**转正 {len(turned)} 个 / 未转正 {len(not_turned)} 个**：\n")

    # 区分稳健转正（三 horizon 一致 f>0 且 n>=30）vs 边缘转正
    robust_turned = []
    marginal_turned = []
    for sid, name, ind, f in turned:
        info = all5[sid]
        b_fs = [info['B_RSI上穿40'][h][4] for h in HORIZONS]
        b_n10 = info['B_RSI上穿40'][10][0]
        all_pos = all(x is not None and x > 0 for x in b_fs)
        if all_pos and b_n10 >= SAMPLE_WARN_N:
            robust_turned.append((sid, name, ind, f))
        else:
            marginal_turned.append((sid, name, ind, f, b_n10, all_pos))

    if robust_turned:
        A(f"**稳健转正**（三 horizon 一致 f>0 且 n≥30）：")
        for sid, name, ind, f in robust_turned:
            A(f"- {sid} {name}（{ind}）：10d f={fmt_f(f)}")
    if marginal_turned:
        A(f"\n**边缘转正**（n<30 或三 horizon 不一致，稳健性存疑）：")
        for sid, name, ind, f, n10, all_pos in marginal_turned:
            flag = []
            if n10 < SAMPLE_WARN_N:
                flag.append(f"n={n10}<30 样本极少")
            if not all_pos:
                flag.append("三 horizon 不一致")
            A(f"- {sid} {name}（{ind}）：10d f={fmt_f(f)}，{'，'.join(flag)}")
    if not_turned:
        A(f"\n**未转正品类**（{len(not_turned)}）：")
        for sid, name, ind, f in not_turned:
            A(f"- {sid} {name}（{ind}）：10d f={fmt_f(f)}")
    A("")

    # 行业模式分析（按大类合并）
    A(f"### 行业模式分析（按大类合并，{n_total_cats} 品类）\n")
    # 把细粒度行业类型合并成大类
    def to大类(ind):
        if '消费' in ind:
            return '消费'
        if '制造' in ind:
            return '制造'
        if '周期' in ind:
            return '周期'
        if 'A股宽基' in ind:
            return 'A股宽基'
        return ind
    by_big = {}
    for sid, name, ind, t, f in b_turn_list:
        big = to大类(ind)
        by_big.setdefault(big, []).append((sid, name, ind, t, f))
    for big_type, items in by_big.items():
        n_total = len(items)
        n_turn = sum(1 for _, _, _, t, _ in items if t)
        n_robust = sum(1 for sid, name, ind, t, f in items if t
                       and all(x is not None and x > 0 for x in [all5[sid]['B_RSI上穿40'][h][4] for h in HORIZONS])
                       and all5[sid]['B_RSI上穿40'][10][0] >= SAMPLE_WARN_N)
        A(f"- **{big_type}**：{n_total} 品类，方案B 转正 {n_turn}/{n_total}（其中稳健转正 {n_robust}/{n_total}）")
        for sid, name, ind, t, f in items:
            info = all5[sid]
            b_n10 = info['B_RSI上穿40'][10][0]
            b_fs = [info['B_RSI上穿40'][h][4] for h in HORIZONS]
            all_pos = all(x is not None and x > 0 for x in b_fs)
            tag = '✅稳健转正' if (t and all_pos and b_n10 >= SAMPLE_WARN_N) else ('⚠️边缘转正' if t else '❌未转正')
            extra = '' if (t and all_pos and b_n10 >= SAMPLE_WARN_N) else (f'（n={b_n10}，三horizon{"一致" if all_pos else "不一致"}）')
            A(f"  - {sid} {name}（{ind}）：f={fmt_f(f)} {tag}{extra}")
    A("")

    # 综合判断（动态：基于实际转正数据）
    A("### 综合判断\n")
    n_robust = len(robust_turned)
    n_marginal = len(marginal_turned)
    n_total_turned = len(turned)
    A(f"方案B（RSI上穿40）在 {n_total_cats} 品类中：**稳健转正 {n_robust}/{n_total_cats}**（三 horizon 一致 f>0 且 n≥30）、"
      f"边缘转正 {n_marginal}/{n_total_cats}、未转正 {len(not_turned)}/{n_total_cats}。")
    if n_robust >= n_total_cats * 0.5:
        A(f"\n**多数品类稳健转正**，方案B 可作为 buy_aux 通用优化方向。")
    elif n_robust >= 2:
        A(f"\n**部分品类稳健转正**，但过半品类未转正或边缘转正，存在品类特异性，需逐品类测后落地，不宜全品类铺开。")
    elif n_robust == 1:
        A(f"\n**方案B 非通用优化方向**。仅 1 个品类稳健转正，多数品类未转正。")
        if robust_turned:
            sid_t, name_t, ind_t, f_t = robust_turned[0]
            A(f"稳健转正：{sid_t} {name_t}（{ind_t}），10d f={fmt_f(f_t)}。")
        if marginal_turned:
            for sid_t, name_t, ind_t, f_t, n10_t, all_pos_t in marginal_turned:
                A(f"边缘转正：{sid_t} {name_t}（{ind_t}），10d f={fmt_f(f_t)}，n={n10_t}，三horizon{'一致' if all_pos_t else '不一致'}。")
    else:
        A(f"\n**方案B 完全非通用**——无稳健转正（n≥30 且三 horizon 一致）。")
        if marginal_turned:
            A(f"仅 {n_marginal} 个边缘转正（n<30 或三 horizon 不一致），稳健性存疑。")
    A("")

    # 方案A 通用性分析（动态）
    A(f"### 方案A（反弹力度2%）通用性分析（{n_total_cats} 品类）\n")
    a_turn_list = []
    for sid in order:
        info = all5[sid]
        a10 = info['A_反弹力度2%'][10]
        a_turn = (a10[4] is not None and a10[4] > 0 and a10[0] >= KELLY_INSUF_N)
        a_fs = [info['A_反弹力度2%'][h][4] for h in HORIZONS]
        a_all_pos = all(x is not None and x > 0 for x in a_fs)
        a_robust = a_turn and a_all_pos and a10[0] >= SAMPLE_WARN_N
        a_turn_list.append((sid, info['name'], info['industry'], a_turn, a_robust, a10[4], a10[0], a_all_pos))
    a_turned = [x for x in a_turn_list if x[3]]
    a_robust_turned = [x for x in a_turn_list if x[4]]
    A(f"方案A 在 {n_total_cats} 品类中：**转正 {len(a_turned)}/{n_total_cats}**（其中稳健转正 {len(a_robust_turned)}/{n_total_cats}）。")
    if a_turned:
        for sid_t, name_t, ind_t, t_t, rt_t, f_t, n_t, ap_t in a_turned:
            tag = '✅稳健转正' if rt_t else '⚠️边缘转正'
            flag = ''
            if n_t < SAMPLE_WARN_N:
                flag = f'（n={n_t}<30 样本警示）'
            elif not ap_t:
                flag = '（三 horizon 不一致）'
            A(f"- {sid_t} {name_t}（{ind_t}）：10d f={fmt_f(f_t)}，n={n_t} {tag}{flag}")
    # A 与 B 转正品类重叠分析
    b_turned_sids = set(x[0] for x in b_turn_list if x[3])
    a_turned_sids = set(x[0] for x in a_turn_list if x[3])
    overlap = b_turned_sids & a_turned_sids
    only_a = a_turned_sids - b_turned_sids
    only_b = b_turned_sids - a_turned_sids
    A(f"\n**A 与 B 转正品类重叠分析**：")
    A(f"- A 转正 {len(a_turned_sids)} 个 / B 转正 {len(b_turned_sids)} 个 / 重叠 {len(overlap)} 个")
    if overlap:
        A(f"- 两方案都转正：{', '.join(sid_NAME_map.get(s, s) for s in overlap)}")
    if only_a:
        A(f"- 仅 A 转正：{', '.join(sid_NAME_map.get(s, s) for s in only_a)}")
    if only_b:
        A(f"- 仅 B 转正：{', '.join(sid_NAME_map.get(s, s) for s in only_b)}")
    if not overlap:
        A(f"- **A 与 B 转正品类不重叠**——两种确认机制（价格力度 vs 动量）适用于不同品类特性，无单一通用方案。")
    A("")

    # 各品类推荐汇总
    A(f"### 各品类推荐方案汇总（{n_total_cats} 品类）\n")
    A("| 品类 | 行业类型 | 推荐方案 | 推荐方案 f | 基线 f | f 改善 | 是否转正 | 备注 |")
    A("|---|---|---|---:|---:|---:|---|---|")
    # 前 8 品类（已落地状态：4 实施 + 4 未实施）
    prior_status = {
        'sw_801110': ('**B_RSI上穿40（已实施）**', +0.1619, -0.3854, '✅ 转正', '已落地（signals.py buy_aux_filter=rsi_cross_40）'),
        'sw_801200': ('维持现状', None, -0.3187, '❌ 未转正', '0 方案转正，维持基线 B1'),
        'sw_801730': ('维持现状', None, -0.2548, '❌ 未转正', 'A 转正但 n=10 样本不足，用户拍板维持现状'),
        'sw_801140': ('**B_RSI上穿40（已实施）**', -0.1412, -0.2496, '❌ 未转正', '退而求其次（胜率+5pp），已落地'),
        'sw_801030': ('**A_反弹力度2%（已实施）**', +0.2043, -0.2087, '✅ 转正', '已落地（signals.py buy_aux_filter=close_above_bl_2pct），n=19 警示'),
        'sh': ('**A_反弹力度2%**', +0.1038, -0.1251, '✅ 转正', '转正，n=26；17 报告推荐，待用户拍板落地'),
        'csi1000': ('**B_RSI上穿40（已实施）**', +0.0347, -0.1950, '✅ 转正', '已落地（signals.py buy_aux_filter=rsi_cross_40），n=19 警示'),
        'hs300': ('**A_反弹力度2%**', +0.0775, -0.1709, '✅ 转正', '转正，n=11；17 报告推荐，待用户拍板落地'),
        # 18 报告品类（传媒已落地 B，综合/钢铁维持现状）
        'sw_801760': ('**B_RSI上穿40（已实施）**', +0.2766, -0.1403, '✅ 转正', '已落地（buy_aux_filter=rsi_cross_40），n=19 警示；A 亦转正但 n=8<10'),
        'sw_801230': ('维持现状', None, -0.1307, '❌ 未转正', '0 方案 10d 转正，B 最接近 f=-2.89% 仍负'),
        'sw_801040': ('维持现状', None, -0.1222, '❌ 未转正', '仅 C 放量 10d 转正 f=+10.99% 但三 horizon 不一致 + C 非已实现 filter + n=17<30'),
    }
    for sid in all_prior_sids:
        info = all5[sid]
        rec, best_f, base_f, turn_str, note = prior_status.get(sid, ('维持现状', None, None, '?', ''))
        delta_pp = (best_f - base_f) * 100 if (best_f is not None and base_f is not None) else 0
        f_str = fmt_f(best_f) if best_f is not None else '-'
        base_str = fmt_f(base_f) if base_f is not None else '-'
        A(f"| {sid} {info['name']} | {info['industry']} | {rec} | {f_str} | {base_str} | "
          f"{delta_pp:+.2f}pp | {turn_str} | {note} |")
    # 本次品类（动态推荐）
    for sid in live_sids:
        info = all5[sid]
        results, n_signals_map, meta = all_cat_results[sid]
        base_f = info['baseline'][10][4]
        # 找最优方案（f 最大且 n>=10）
        candidates = []
        for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
            n, m, wr, pl, f, cls, lbl = info[sn][10]
            if f is not None and n >= KELLY_INSUF_N:
                candidates.append((sn.split('_')[0], sn, f, n, lbl))
        if candidates:
            best_letter, best_sn, best_f, best_n, best_lbl = max(candidates, key=lambda x: x[2])
            is_turn = best_f > 0
            delta_pp = (best_f - base_f) * 100 if base_f is not None else 0
            if is_turn:
                rec = f"**{best_sn}**"
                note = f"转正，n={best_n}"
            else:
                # 看胜率提升最多的
                wr_candidates = []
                for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
                    n, m, wr, pl, f, cls, lbl = info[sn][10]
                    if n >= KELLY_INSUF_N:
                        wr_candidates.append((sn.split('_')[0], sn, wr, n, f))
                best_wr_letter, best_wr_sn, best_wr, best_wr_n, best_wr_f = max(wr_candidates, key=lambda x: x[2])
                rec = f"维持现状（或退而求其次选 {best_wr_sn}）"
                note = f"0 方案转正；最优 f={fmt_f(best_f)}（{best_letter}），n={best_n}"
        else:
            rec = "维持现状"
            note = "样本均不足"
            best_f = None
            is_turn = False
            delta_pp = 0
        A(f"| {sid} {info['name']} | {info['industry']} | {rec} | "
          f"{fmt_f(best_f) if best_f is not None else '-'} | {fmt_f(base_f)} | "
          f"{delta_pp:+.2f}pp | {'✅ 转正' if is_turn else '❌ 未转正'} | {note} |")
    A("")

    return L


# ===================== 主流程 =====================

def main():
    # 命令行支持：python backtest_buy_aux_batch.py [sid1 sid2 ...]
    if len(sys.argv) > 1:
        cats = [(sid, sid_NAME_map.get(sid, sid)) for sid in sys.argv[1:]]
    else:
        cats = DEFAULT_CATEGORIES

    # 报告路径：按品类 sid 拼接文件名（保持与历史报告 14/15/16/17 命名一致）
    # 默认放到 /Users/linhuichen/code/trade/ 下，文件名 18-行业buy_aux回测-{name1}-{name2}-{name3}.md
    global REPORT
    if REPORT is None:
        names = [sid_NAME_map.get(sid, sid) for sid, _ in cats]
        # 报告编号：14~25 已用，本次从 26 开始
        report_num = 26
        REPORT = f'/Users/linhuichen/code/trade/{report_num:02d}-行业buy_aux回测-{"".join(n+"-" for n in names[:-1])}{names[-1]}.md'

    print(f"待测品类 {len(cats)} 个：{[sid for sid, _ in cats]}")
    print(f"报告输出: {REPORT}")

    # 加载 signal_stats.json 基线用于核对
    import json
    try:
        with open('/Users/linhuichen/code/trade/data/signal_stats.json') as f:
            stats = json.load(f)
    except Exception:
        stats = {}

    all_cat_results = {}
    for sid, sid_name in cats:
        print(f"\n=== {sid} {sid_name} ===")
        results, n_signals_map, meta = run_one_category(sid, sid_name)
        if results is None:
            print(f"  {sid} 数据加载失败，跳过")
            continue
        all_cat_results[sid] = (results, n_signals_map, meta)
        print(f"  数据：{meta['rows']} 行，{meta['date_start']} ~ {meta['date_end']}")
        print(f"  C1 主买信号 {meta['c1_buy_n']} 个")
        for sn, _, _ in SCHEMES:
            n10, m10, wr10, pl10, f10, cls10, lbl10 = results[sn][10]
            print(f"  {sn}: 信号 {n_signals_map[sn]} | 10d n={n10} 胜率={fmt_pct(wr10*100)} "
                  f"盈亏比={fmt_pl(pl10)} f={fmt_f(f10)} {lbl10}")

    # 生成报告
    cat_names = ' / '.join(f"{sid} {sid_NAME_map.get(sid, sid)}" for sid, _ in cats)
    L = []
    A = L.append
    A(f"# buy_aux（B1 辅买）优化回测 — 行业品类批量（{' / '.join(sid_NAME_map.get(sid, sid) for sid, _ in cats)}）\n")
    A("- 生成日期：2026-07-08")
    A(f"- 标的：{len(cats)} 个 A 股指数（宽基/风格/行业）（{cat_names}）")
    A("- 数据源：data/sentiment.db index_daily")
    A("- horizon：5d / 10d / 20d 三 horizon（10d 主指标与前端 tips 一致，5d/20d 验证一致性）")
    A("- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 signals.py `_rsi`）")
    A("- BB 算法：window=20, n_std=2.0, std ddof=0（复刻 signals.py `_bollinger`）")
    A("- 凯利公式：f* = (b·p - (1-p))/b，p=胜率 b=盈亏比；f>0=建议，f≤0=不建议，n<10=样本不足")
    A("- 买点胜率=收益>0占比（信号后 N 日上涨才算对）；盈亏比=平均盈利(涨)/平均亏损(跌)")
    A("- 去重：C1 主买（RSI 上穿 30）与 buy_aux 同日触发时保留 C1，不重复发 buy_aux（与 signals.py 一致）")
    A("- 3 个改进方案：A(反弹力度2%) / B(RSI上穿40) / C(放量1.2倍)（与前 8 品类同方案，横向可比）")
    A("- 每品类独立判断（不套同一方案）")
    A("")
    A("> 背景：用户要求把凯利不建议（f≤0）的 buy_aux 逐个品类优化。已完成 11 品类：")
    A("> - **家电 sw_801110**：方案B（RSI上穿40）转正 f -38%→+16%，已实施")
    A("> - **基础化工 sw_801030**：方案A（反弹2%）转正 f -21%→+20%，已实施（n=19 警示）")
    A("> - **轻工 sw_801140**：方案B 退而求其次（胜率+5pp，f 仍-14%），已实施")
    A("> - **csi1000 中证1000**：方案B（RSI上穿40）转正 f -19.5%→+3.47%，已实施（n=19 警示）")
    A("> - **传媒 sw_801760**：方案B（RSI上穿40）转正 f -14%→+28%，已实施（n=19 警示）")
    A("> - **商贸 sw_801200 / 电力设备 sw_801730 / sh 上证 / hs300 沪深300 / 综合 sw_801230 / 钢铁 sw_801040**：维持现状")
    A(">")
    A("> **11 品类通用性结论**：方案B（RSI上穿40）稳健转正 1/11（家电 n≥30）、边缘转正 3/11（csi1000/传媒/电力设备，n<30 或三 horizon 不一致）、未转正 7/11；")
    A("> 方案A（反弹2%）转正 5/11 但全 n<30 稳健 0/11；A 与 B 转正品类重叠 1（传媒）——无单一通用方案。")
    A(">")
    A(f"> 本次测 {len(cats)} 个品类（{' / '.join(sid_NAME_map.get(sid, sid) for sid, _ in cats)}），")
    A(f"> A 股宽基/风格/行业优先（有涨跌停板，RSI 超卖反弹确定性高于港股/全球）。**每个品类独立判断**（不套用同一方案）。\n")

    A("| 品类 | 中文名 | 行业类型 | 10d 胜率 | 10d 盈亏比 | 10d n | 10d f | 10d 均值 |")
    A("|---|---|---|---:|---:|---:|---:|---:|")
    for sid, sid_name in cats:
        if sid in all_cat_results:
            results, n_signals_map, meta = all_cat_results[sid]
            n, m, wr, pl, f, cls, lbl = results['基线_B1'][10]
            A(f"| {sid} | {sid_name} | {INDUSTRY_TYPE.get(sid, '?')} | "
              f"{fmt_pct(wr*100)} | {fmt_pl(pl)} | {n} | {fmt_f(f)} | {fmt_mean(m)} |")
    A("")

    # 各品类一节
    for sid, sid_name in cats:
        if sid not in all_cat_results:
            continue
        results, n_signals_map, meta = all_cat_results[sid]
        baseline_target = stats.get(sid, {}).get('buy_aux', {})
        # stats.json 用 5d/10d/20d 键，转成 {5: ..., 10: ..., 20: ...}
        bt = {}
        for h in HORIZONS:
            key = f"{h}d"
            if key in baseline_target:
                bt[h] = baseline_target[key]
        section = render_category_section(sid, sid_name, results, n_signals_map, meta, baseline_target=bt)
        L.extend(section)

    # 汇总
    summary = render_summary(all_cat_results)
    L.extend(summary)

    # 收尾
    A("## 收尾\n")
    A("- 每品类独立判断，用户逐品类选方案")
    A(f"- {len(PRIOR_CATEGORIES) + len(cats)} 品类里方案A/B 转正的有哪些、不转正的有哪些，是否看出行业模式 → 见汇总节")
    A("- 诚实结论：见各品类「诚实结论」节 + 汇总「综合判断」节")
    A("- 样本数警示：各方案 n<30 已标注 ⚠️，n<10 标注「样本不足」")
    A("- 过拟合警示：3 方案参数（2% / 40 / 1.2 倍）均业界常用值，非历史调参，但仍有选择性偏差风险")
    A("")
    A("---")
    A("")
    A("*本报告由 `a-stock-data/backtest_buy_aux_batch.py` 自动生成。"
      "回测独立复刻 signals.py 的 B1 buy_aux 逻辑，不 import app，不改 app/ 代码，不改 DB。"
      "凯利公式参考仓位，非投资建议。*")

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))
    print(f"\n报告已写入: {REPORT}")
    print(f"\n=== 汇总 ===")
    for sid in [c[0] for c in cats]:
        if sid not in all_cat_results:
            continue
        results, n_signals_map, meta = all_cat_results[sid]
        print(f"\n{sid} {sid_NAME_map[sid]}:")
        for sn, _, _ in SCHEMES:
            n10, m10, wr10, pl10, f10, cls10, lbl10 = results[sn][10]
            print(f"  {sn}: 10d f={fmt_f(f10)} ({lbl10}) 胜率={fmt_pct(wr10*100)} n={n10} 信号={n_signals_map[sn]}")


# sid -> name 映射（用于报告里显示中文名）
sid_NAME_map = {
    'sw_801730': '电力设备',
    'sw_801140': '轻工制造',
    'sw_801030': '基础化工',
    'sw_801110': '家用电器',
    'sw_801200': '商贸零售',
    'sh': '上证指数',
    'csi1000': '中证1000',
    'hs300': '沪深300',
    'sw_801760': '传媒',
    'sw_801230': '综合',
    'sw_801040': '钢铁',
    # 第 20 批新增（A股宽基/风格 + 行业）
    'csi500': '中证500',
    'cyb': '创业板指',
    'sz_div': '深证红利',
    'sw_801050': '有色金属',
    'sw_801120': '食品饮料',
    'sw_801150': '医药生物',
    # 第 21 批新增（剩余品类逐个优化）
    'kc50': '科创50',
    'sz': '深证成指',
    'sw_801130': '纺织服饰',
    'sw_801160': '公用事业',
    'sw_801170': '交通运输',
    'sw_801180': '房地产',
    'sw_801210': '社会服务',
    'sw_801770': '通信',
    'sw_801750': '计算机',
    'sw_801740': '国防军工',
    'sw_801970': '环保',
    'sw_801010': '农林牧渔',
    'sw_801080': '电子',
    'sw_801710': '建筑材料',
    'sw_801720': '建筑装饰',
    'sw_801780': '银行',
    'sw_801790': '非银金融',
    'sw_801890': '机械设备',
    'sw_801950': '煤炭',
    'sw_801960': '石油石化',
    'sw_801980': '美容护理',
    'csi_div': '中证红利',
    'div_lowvol': '红利低波',
    'hsi': '恒生指数',
    'hstech': '恒生科技',
    'hscei': '恒生国企',
    'us_dji': '道琼斯',
    'us_ixic': '纳斯达克',
    'us_spx': '标普500',
    'us_ndx': '纳斯达克100',
}


if __name__ == '__main__':
    main()
