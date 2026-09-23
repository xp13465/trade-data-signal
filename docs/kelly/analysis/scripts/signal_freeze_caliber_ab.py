# -*- coding: utf-8 -*-
"""固化快照修正 vs 回测口径前视偏差: A/B 双口径前端同构复刻(2026-09-23 调研落档)

来源: /tmp/kelly_s06_repro.py(researcher 前端同构复刻脚本),参数化改造后落档本目录。
用途: 对「前端全信号表口径」(评级三区并集 + S06动态降亏(a9/new14 按日切) + positionCap K=1 每日池
      + 峰值资金收益率)做 A/B 双口径对比:
  - A(现状): 回测信号集 = signal_daily 全表最终版(含晚到)
  - B(固化): 回测信号集 = 剔除 8-12~9-22 共 70 条晚到后的 signal_daily
复刻对象: 前端 lab 页「全信号表 · 最后结果」卡(signal_kelly_trades.json -> 前端实时过滤/重算)。
口径要点:
  - 三区并集 = rating_high/rating_mid/rating_low 之 A 模式(固定10天卖出)并集,同日同基笔去重(每日池 K=1 只留最优 1 笔)
  - S06 动态基座按 signal_date 逐日取 kelly_mode_s06_state.json(覆盖期外 fallback off_base=new14)
  - profit 用前端实时重算(_kellyRecomputeTrade, 默认费率 etf_main 万0.5/min0.1 + 滑点 0.1% + 经手费)
  - rmh(峰值资金收益率) = 总盈亏 / 峰值同时持仓资金 × 100, 峰值资金按每笔(买日+10000/卖日-10000)现金流叠加求最大
  - 历史对账锚点: 9-22 旧数据版本(线上产物到 9-15) A=549笔/+161.63%(tp 161,629/峰值10万)、K=155.42%;
    当前 9-23 数据版本(线上到 9-22, 与 /tmp/bk_env/A 一致) A=554笔/+154.34%(tp 154,336/峰值10万)

用法(路径可配置,不依赖 /tmp; --trades-json 可传多次配对 --label):
  python3 signal_freeze_caliber_ab.py \
      --trades-json /tmp/bk_env/A/out/signal_kelly_trades.json --label A \
      --trades-json /tmp/bk_env/B/out/signal_kelly_trades.json --label B \
      2>run.log        # 详细过程打到 stderr
  python3 signal_freeze_caliber_ab.py --json <上同>   # 机器可读 JSON 汇总
"""
import argparse
import datetime
import json
import sys

DEFAULT_ROOT = "/Users/linhuichen/code/trade"
DEFAULT_S06 = DEFAULT_ROOT + "/static-site/data/kelly_mode_s06_state.json"
DEFAULT_FEATURES = DEFAULT_ROOT + "/static-site/data/kelly_loss_features.json"

# ---- 费率预设(lab.js KELLY_FEE_PRESETS 同源, 默认档 etf_def=万3/最低5, 与前端默认及页面对账口径一致) ----
FEE_PRESETS = {
    "zero":      dict(commission_rate=0,       min_commission=0,   slippage=0,     transfer_fee_rate_sh=0,       stamp_duty_rate=0),
    "etf_def":   dict(commission_rate=0.0003,  min_commission=5,   slippage=0.001, transfer_fee_rate_sh=0.00001, stamp_duty_rate=0),   # 万3 最低5 当前(默认)
    "etf_main":  dict(commission_rate=0.00005, min_commission=0.1, slippage=0.001, transfer_fee_rate_sh=0.00001, stamp_duty_rate=0),   # 万0.5 最低0.1
    "etf_cheap": dict(commission_rate=0.00001, min_commission=0,   slippage=0.001, transfer_fee_rate_sh=0.00001, stamp_duty_rate=0),   # 万0.1 免5
    "stock_def": dict(commission_rate=0.0005,  min_commission=5,   slippage=0.002, transfer_fee_rate_sh=0.00001, stamp_duty_rate=0.0005),
}

# ---------------------------------------------------------------------------
# 键集定义(common.js _KELLY_FADE_MODE_PRESETS)
KEYS_A9 = [
    "excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial",
    "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15",
    "bullAuxBackupStop", "t1LowTurnSpecial", "q1QvixLowPct", "m1MarginDownBull",
    "v1HighVol20", "r1VolRatioLow", "k3ConceptBuy", "r2bSpecialGlobal", "r2gLowRatingQ3",
]
KEYS_NEW14 = [
    "r10May6NonMay", "greedy15", "janMidSpecial", "k2c5HkChase", "k3ConceptBuy",
    "declinePhaseSpecial", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield",
    "q1QvixLowPct", "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup", "r2bSpecialGlobal",
]
BASE_KEYS = {'a9': set(KEYS_A9), 'new14': set(KEYS_NEW14)}

# ---- _KELLY_FADE_LEGACY_SPECS(common.js, gate=0 + gate=1) ----
LEGACY_SPECS = {
    "excludeAux": {"gate": 0, "any": [{"sig": "buy_aux"}]},
    "marketTiming": {"gate": 0, "any": [{"mstateNotTrue": 1}]},
    "excludeMonth": {"gate": 0, "any": [{"mmIn": ["03", "05"]}]},
    "excludeRatingLow": {"gate": 0, "any": [{"ratingIsLow": 1}]},
    "excludeAuxCross": {"gate": 0, "any": [{"sig": "buy_aux", "mmIn": ["03", "05"]}]},
    "excludeSpecialBear": {"gate": 0, "any": [{"sig": "buy_special", "tierIn": ["熊市·主跌", "下降期"]}]},
    "legacyMa60Special": {"gate": 0, "any": [{"sig": "buy_special", "mstateFalse": 1}]},
    "declinePhaseSpecial": {"gate": 0, "any": [{"sig": "buy_special", "tierAll": "下降期"}]},
    "excludeSpecialBearCyb": {"gate": 0, "any": [{"sig": "buy_special", "tierCybIn": ["熊市·主跌", "下降期"]}]},
    "bullAuxBackupStop": {"gate": 0, "any": [{"sigIn": ["buy_aux", "buy_backup"], "tier": "牛市·主升"}]},
    "n1MarTueHigh": {"gate": 1, "any": [{"mm": "03", "wd": 2, "bpb": "high"}]},
    "n2NovSpecialIndustry": {"gate": 1, "any": [{"sig": "buy_special", "mm": "11", "mkt": "industry"}]},
    "r8PureNonMay": {"gate": 1, "any": [
        {"mm": "03", "wd": 2, "bpb": "high"},
        {"sig": "buy_special", "mm": "11", "mkt": "industry"},
        {"sig": "buy_special", "mm": "11", "wd": 0}]},
    "n3NovSpecialMon": {"gate": 1, "any": [{"sig": "buy_special", "mm": "11", "wd": 0}]},
    "n4AMay": {"gate": 1, "any": [{"mkt": "a", "mm": "05"}]},
    "r7MayReinforced": {"gate": 1, "any": [
        {"mkt": "a", "mm": "05"}, {"rat": "mid", "mm": "05"}, {"mm": "05", "bpb": "vlow"},
        {"mm": "03", "wd": 2, "bpb": "high"}, {"sig": "buy_special", "mm": "11", "mkt": "industry"},
        {"sig": "buy_special", "mm": "11", "wd": 0}]},
    "n5MayVlow": {"gate": 1, "any": [{"mm": "05", "bpb": "vlow"}]},
    "n6MidMay": {"gate": 1, "any": [{"rat": "mid", "mm": "05"}]},
    "r10May6NonMay": {"gate": 1, "any": [
        {"mm": "05"}, {"mm": "03", "wd": 2, "bpb": "high"},
        {"sig": "buy_special", "mm": "11", "mkt": "industry"},
        {"sig": "buy_special", "mm": "11", "wd": 0},
        {"sig": "buy_special", "mm": "11", "bpb": "low"},
        {"sig": "buy_special", "mm": "03", "mkt": "industry"},
        {"mm": "03", "wd": 2, "sig": "buy_aux"}]},
    "v4cSimple": {"gate": 1, "any": [{"mm": "03", "wd": 2, "sig": "buy_aux"}]},
    "v4b": {"gate": 1, "any": [{"mkt": "a", "mm": "05", "sig": "buy_special", "etf": "related"}]},
    "greedy7": {"gate": 1, "any": [
        {"sig": "buy_special", "mm": "05"}, {"sig": "buy_special", "mm": "11", "mkt": "concept"},
        {"sig": "buy_special", "mm": "03"}, {"sig": "buy_aux", "mm": "01"},
        {"q": 2, "bpb": "vlow", "sig": "buy_aux", "mkt": "concept"},
        {"sig": "buy", "mm": "01"}, {"mm": "03", "wd": 2, "mkt": "concept", "rat": "low"}]},
    "v4d": {"gate": 1, "any": [{"mm": "12", "wd": 1, "sig": "buy_aux", "tsMax": 50}]},
    "v4j": {"gate": 1, "any": [{"mm": "05", "bpb": "vlow", "sig": "buy_special"}]},
    "v4i": {"gate": 1, "any": [{"sig": "buy_special", "mm": "05", "mkt": "concept", "wd": 0}]},
    "greedy10": {"gate": 1, "any": [
        {"sig": "buy_special", "mm": "05"}, {"sig": "buy_special", "mm": "11", "mkt": "concept"},
        {"sig": "buy_special", "mm": "03"}, {"sig": "buy_aux", "mm": "01"},
        {"q": 2, "bpb": "vlow", "sig": "buy_aux", "mkt": "concept"},
        {"sig": "buy", "mm": "01"}, {"mm": "03", "wd": 2, "mkt": "concept", "rat": "low"},
        {"sig": "buy_aux", "mm": "12", "tsMax": 50}, {"mm": "06", "bpb": "vlow", "rat": "low"},
        {"sig": "buy_aux", "mm": "05"}]},
    "v4f": {"gate": 1, "any": [{"sig": "buy", "mm": "06", "wd": 2, "etf": "related"}]},
    "v4g": {"gate": 1, "any": [{"mkt": "global", "q": 1, "sig": "buy_aux", "rat": "low"}]},
    "v4m": {"gate": 1, "any": [{"sig": "buy_special", "mm": "09", "wd": 2}]},
    "v4k": {"gate": 1, "any": [{"sig": "buy", "mm": "01", "bpb": "high"}]},
    "greedy15": {"gate": 1, "any": [
        {"sig": "buy_special", "mm": "05"}, {"sig": "buy_special", "mm": "11", "mkt": "concept"},
        {"sig": "buy_special", "mm": "03"}, {"sig": "buy_aux", "mm": "01"},
        {"q": 2, "bpb": "vlow", "sig": "buy_aux", "mkt": "concept"},
        {"sig": "buy", "mm": "01"}, {"mm": "03", "wd": 2, "mkt": "concept", "rat": "low"},
        {"sig": "buy_aux", "mm": "12", "tsMax": 50}, {"mm": "06", "bpb": "vlow", "rat": "low"},
        {"sig": "buy_aux", "mm": "05"}, {"sig": "buy_special", "mm": "11", "mkt": "industry"},
        {"mm": "04", "wd": 1, "mkt": "concept", "tsMax": 50},
        {"mkt": "global", "q": 1, "sig": "buy_aux", "rat": "low"},
        {"mm": "01", "bpb": "low", "sig": "buy_special", "mkt": "concept"},
        {"sig": "buy_special", "mm": "09", "wd": 2}]},
    "a5NovMidSpecial": {"gate": 1, "any": [{"sig": "buy_special", "mm": "11", "ddMin": 11, "ddMax": 20}]},
    "a45NovMidLateSpecial": {"gate": 1, "any": [{"sig": "buy_special", "mm": "11", "ddMin": 11}]},
    "janMidRating": {"gate": 1, "any": [{"mm": "01", "ddMin": 11, "ddMax": 20, "rat": "mid"}]},
    "janMidSpecial": {"gate": 1, "any": [{"sig": "buy_special", "mm": "01", "ddMin": 11, "ddMax": 20}]},
    "k2c5HkChase": {"gate": 1, "any": [{"sigIn": ["buy_special", "buy_backup"], "mkt": "hk"}]},
    "k3ConceptBuy": {"gate": 1, "any": [{"sig": "buy", "mkt": "concept"}]},
}
FRONT_KEY_ORDER = [
    "excludeAux", "marketTiming", "excludeMonth", "excludeRatingLow", "excludeAuxCross",
    "excludeSpecialBear", "legacyMa60Special", "declinePhaseSpecial", "excludeSpecialBearCyb",
    "bullAuxBackupStop",
]
GATE_KEY_ORDER = [
    "n1MarTueHigh", "n2NovSpecialIndustry", "r8PureNonMay", "n3NovSpecialMon", "n4AMay",
    "r7MayReinforced", "n5MayVlow", "n6MidMay", "r10May6NonMay", "v4cSimple", "v4b",
    "greedy7", "v4d", "v4j", "v4i", "greedy10", "v4f", "v4g", "v4m", "v4k", "greedy15",
    "a5NovMidSpecial", "a45NovMidLateSpecial", "janMidRating", "janMidSpecial",
    "k2c5HkChase", "k3ConceptBuy",
]
MONTH_MASK = {
    "a5NovMidSpecial": 1 << 10, "a45NovMidLateSpecial": 1 << 10, "n1MarTueHigh": 1 << 2,
    "n2NovSpecialIndustry": 1 << 10, "r8PureNonMay": (1 << 2) | (1 << 10),
    "n3NovSpecialMon": 1 << 10, "n4AMay": 1 << 4,
    "r7MayReinforced": (1 << 4) | (1 << 2) | (1 << 10), "n5MayVlow": 1 << 4,
    "n6MidMay": 1 << 4, "r10May6NonMay": (1 << 4) | (1 << 2) | (1 << 10),
    "v4cSimple": 1 << 2, "v4b": 1 << 4,
    "greedy7": (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5),
    "v4d": 1 << 11, "v4j": 1 << 4, "v4i": 1 << 4,
    "greedy10": (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5) | (1 << 11),
    "v4f": 1 << 5, "v4g": (1 << 0) | (1 << 1) | (1 << 2), "v4m": 1 << 8, "v4k": 1 << 0,
    "greedy15": (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 8) | (1 << 10) | (1 << 11),
    "janMidRating": 1 << 0, "janMidSpecial": 1 << 0, "k2c5HkChase": 0x1FFF, "k3ConceptBuy": 0x1FFF,
}


def Number(x):
    try:
        return float(x)
    except Exception:
        return 999.0


def weekday_py(bd):
    s = str(bd)
    if len(s) < 8:
        return -1
    y, m, dd = int(s[0:4]), int(s[4:6]), int(s[6:8])
    return datetime.date(y, m, dd).weekday()


def bpb(price):
    if price is None:
        return ""
    if price <= 0.841441:
        return "vlow"
    if price <= 1.015314:
        return "low"
    if price <= 1.194593:
        return "mid"
    if price <= 1.446645:
        return "high"
    return "vhigh"


def active_month_mask(keys):
    m = 0
    for k in MONTH_MASK:
        if k in keys:
            m |= MONTH_MASK[k]
    return m


class _CaliberRunner:
    """单个 trades json 的前端同构复刻(每个实例独立持有 FI/dims/特征表)。"""

    def __init__(self, trades_path, s06_path, feat_path, buy_amount=10000.0, fee_params=None):
        self.buy_amount = buy_amount
        self.fee = fee_params or FEE_PRESETS['etf_def']
        d = json.load(open(trades_path))
        self.d = d
        self.FI = {f: i for i, f in enumerate(d['fields'])}
        self.quads = d['quadrants']
        # S06 state 按日取基座(a9/new14)
        s06 = json.load(open(s06_path))
        self.s06_by_date = {}
        for row in s06['daily']:
            self.s06_by_date[str(row['date']).replace('-', '')] = row['effective_mode']
        cs = str(s06['coverage_start']).replace('-', '')
        ce = str(s06['coverage_end']).replace('-', '')
        self.cs, self.ce = cs, ce
        self.off_base = s06['off_base']
        # T1 规格+特征
        feat = json.load(open(feat_path))
        self.spec_map = {r['key']: r for r in feat['meta']['rules']}
        self.features = feat['features']
        # trade dims(与 _kellyBuildTradeDims 同构)
        dims = {}
        for qk, qv in d['quadrants'].items():
            parts = qk.split('_')
            dim_type, dim_val = parts[0], '_'.join(parts[1:])
            if dim_type not in ('rating', 'etf', 'sig', 'mkt'):
                continue
            for mk, arr in qv.items():
                for t in arr:
                    key = '|'.join([
                        str(t[self.FI['signal_date']] or ''), str(t[self.FI['index_id']] or ''),
                        str(t[self.FI['signal']] or ''), str(t[self.FI['buy_date']] or ''),
                        str(t[self.FI['etf_code']] or ''), str(t[self.FI['sell_date']] or '')])
                    dims.setdefault(key, {})[dim_type] = dim_val
        self.trade_dims = dims

    # ----- S06 -----
    def s06_base_for_date(self, ds):
        ds = str(ds).replace('-', '')
        if ds not in self.s06_by_date:
            if (ds < self.cs) or (ds > self.ce):
                return self.off_base, 'out_of_range_fallback'
            return None, 'no_row'  # fail-open
        b = self.s06_by_date[ds]
        if b not in ('a9', 'new14'):
            return self.off_base, 'bad_mode_fallback'
        return b, 'ok'

    # ----- 过滤 ----
    def spec_hit(self, key, c):
        sp = LEGACY_SPECS.get(key)
        if not sp:
            return False
        for p in sp['any']:
            ok = True
            if p.get('sig') is not None and c['sig'] != p['sig']:
                ok = False
            if ok and p.get('sigIn') is not None and c['sig'] not in p['sigIn']:
                ok = False
            if ok and p.get('mm') is not None and c['mm'] != p['mm']:
                ok = False
            if ok and p.get('mmIn') is not None and c['mm'] not in p['mmIn']:
                ok = False
            if ok and p.get('ddMin') is not None and not (c['dd'] >= p['ddMin']):
                ok = False
            if ok and p.get('ddMax') is not None and not (c['dd'] <= p['ddMax']):
                ok = False
            if ok and p.get('wd') is not None and c['wd'] != p['wd']:
                ok = False
            if ok and p.get('bpb') is not None and c['bpb'] != p['bpb']:
                ok = False
            if ok and p.get('q') is not None and c['q'] != p['q']:
                ok = False
            if ok and p.get('tsMax') is not None and not (Number(c['ts']) < p['tsMax']):
                ok = False
            if ok and p.get('mkt') is not None and c['mktD'] != p['mkt']:
                ok = False
            if ok and p.get('etf') is not None and c['etfD'] != p['etf']:
                ok = False
            if ok and p.get('rat') is not None and c['ratD'] != p['rat']:
                ok = False
            if ok and p.get('tier') is not None and c['tier'] != p['tier']:
                ok = False
            if ok and p.get('tierIn') is not None and c['tier'] not in p['tierIn']:
                ok = False
            if ok and p.get('tierAll') is not None and c['tierAll'] != p['tierAll']:
                ok = False
            if ok and p.get('tierCybIn') is not None and c['tierCyb'] not in p['tierCybIn']:
                ok = False
            if ok and p.get('ratingIsLow') is not None and c['rating'] != 'low':
                ok = False
            if ok and p.get('mstateNotTrue') is not None and c['mstate'] is True:
                ok = False
            if ok and p.get('mstateFalse') is not None and c['mstate'] is not False:
                ok = False
            if ok:
                return True
        return False

    def loss_rule_hit(self, key, ctx):
        spec = self.spec_map.get(key)
        if not spec:
            return False
        if spec.get('feature'):
            series = self.features.get(spec['feature'])
            v = series.get(str(ctx['date'])) if series else None
            if v is None:
                return False
            if spec['direction'] == 'low':
                if not (v < spec['threshold']):
                    return False
            else:
                if not (v > spec['threshold']):
                    return False
        if spec.get('sig') is not None and str(ctx['sig'] or '') != spec['sig']:
            return False
        if spec.get('tier') is not None and str(ctx['tier'] or '') != spec['tier']:
            return False
        if spec.get('mkt') is not None and str(ctx['mkt'] or '') != spec['mkt']:
            return False
        if spec.get('track_tier') is not None:
            tt = str(ctx.get('track_tier') or '')
            arr = spec['track_tier'] if isinstance(spec['track_tier'], list) else [spec['track_tier']]
            if tt not in arr:
                return False
        if spec.get('rating') is not None:
            if str(ctx.get('rating') or '') != spec['rating']:
                return False
            tv = 999 if (ctx.get('ts') is None or ctx.get('ts') == '') else Number(ctx['ts'])
            if not (tv < spec['max_ts']):
                return False
            if str(ctx.get('smonth') or '') not in spec.get('months', []):
                return False
        return True

    def passes_fade(self, t):
        FI = self.FI
        keys = self.cur_keys
        # gate=0
        fc = {'sig': str(t[FI['signal']] or ''), 'mm': str(t[FI['buy_date']] or '')[4:6],
              'rating': str(t[FI['rating']] or ''), 'tier': str(t[FI['market_tier']] or ''),
              'tierAll': str(t[FI['market_tier_all']] or ''), 'tierCyb': str(t[FI['market_tier_cyb']] or ''),
              'mstate': t[FI['market_state']]}
        for k in FRONT_KEY_ORDER:
            if k in keys and self.spec_hit(k, fc):
                return False
        # gate=1
        g1_on = any(k in keys for k in GATE_KEY_ORDER)
        if g1_on:
            mmask = active_month_mask(keys)
            mm = str(t[FI['buy_date']] or '')[4:6]
            m_int = int(mm) if mm else 0
            if m_int and not (mmask & (1 << (m_int - 1))):
                return True
            bd = str(t[FI['buy_date']] or '')
            dk = '|'.join([str(t[FI['signal_date']] or ''), str(t[FI['index_id']] or ''), str(t[FI['signal']] or ''), bd, str(t[FI['etf_code']] or ''), str(t[FI['sell_date']] or '')])
            dims = self.trade_dims.get(dk, {})
            feats = {'mm': bd[4:6], 'dd': int(bd[6:8]) if len(bd) >= 8 else 0, 'sig': str(t[FI['signal']] or ''),
                     'wd': weekday_py(bd), 'bpb': bpb(t[FI['buy_price']]), 'mktD': dims.get('mkt', ''),
                     'ratD': dims.get('rating', ''), 'ts': Number(t[FI['track_score']]) if t[FI['track_score']] is not None else 999,
                     'etfD': str(t[FI['track_tier']] or ''), 'q': (int(mm) + 2) // 3 if mm else 0}
            for k in GATE_KEY_ORDER:
                if k in keys and self.spec_hit(k, feats):
                    return False
        # T1
        t1_keys = [k for k in self.spec_map if k in keys]
        if t1_keys:
            sd = str(t[FI['signal_date']] or '')
            bd = str(t[FI['buy_date']] or '')
            dk = '|'.join([sd, str(t[FI['index_id']] or ''), str(t[FI['signal']] or ''), bd, str(t[FI['etf_code']] or ''), str(t[FI['sell_date']] or '')])
            ctx20 = {'sig': str(t[FI['signal']] or ''), 'mkt': self.trade_dims.get(dk, {}).get('mkt', ''),
                     'tier': str(t[FI['market_tier']] or ''), 'track_tier': 'null' if t[FI['track_tier']] is None else str(t[FI['track_tier']] or ''),
                     'date': bd, 'smonth': sd[4:6], 'rating': str(t[FI['rating']] or ''), 'ts': t[FI['track_score']]}
            for k in t1_keys:
                if self.loss_rule_hit(k, ctx20):
                    return False
        return True

    # ----- 费率重算(前端 _kellyRecomputeTrade 同构) -----
    def recompute_profit(self, t):
        FI = self.FI
        bp = t[FI['buy_price']] or 0
        sp = t[FI['sell_price']] or 0
        cp = t[FI['current_price']] or 0
        ec = t[FI['etf_code']] or ''
        sellDate = t[FI['sell_date']] or ''
        buyAmount = self.buy_amount
        if bp <= 0:
            return 0.0
        KELLY_ORIG_SLIPPAGE = 0.001
        closeBuy = bp / (1 + KELLY_ORIG_SLIPPAGE)
        closeSell = (sp / (1 - KELLY_ORIG_SLIPPAGE)) if sellDate else cp
        c = self.fee['commission_rate']
        s = self.fee['slippage']
        minC = self.fee['min_commission']
        sh = self.fee['transfer_fee_rate_sh'] if (ec.startswith('51') or ec.startswith('58')) else 0.0
        stamp = self.fee['stamp_duty_rate']
        buyPriceNew = closeBuy * (1 + s)
        if buyPriceNew <= 0:
            return 0.0
        sharesNew = buyAmount / (buyPriceNew * (1 + c + sh))
        grossNew = sharesNew * buyPriceNew
        commBuy = grossNew * c
        if commBuy < minC:
            sharesNew = (buyAmount - minC) / (buyPriceNew * (1 + sh))
            grossNew = sharesNew * buyPriceNew
            commBuy = minC
        sellPriceNew = closeSell * (1 - s)
        sellAmountNew = sharesNew * sellPriceNew
        commSell = max(sellAmountNew * c, minC)
        transferFeeSell = sellAmountNew * sh
        stampDuty = sellAmountNew * stamp
        netNew = sellAmountNew - commSell - transferFeeSell - stampDuty
        return round(netNew - buyAmount, 2)

    # ----- 前端口径主流程(三区并集 -> S06过滤 -> 每日池K1 -> 统计) -----
    def run_caliber(self, mode='A'):
        """返回前端口径对比统计 dict:
        {n, tp, maxCC, rmh, pool_n, kept_pool_n, year_detail}"""
        FI = self.FI
        RATING_RANK = {'high': 0, 'mid': 1, 'low': 2, '': 3}
        SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3, '': 9}
        pool = []
        for rk in ['rating_high', 'rating_mid', 'rating_low']:
            for t in self.quads[rk][mode]:
                pool.append(t)
        stat_mode = {'a9': 0, 'new14': 0, 'out_of_range_fallback': 0, 'no_row': 0, 'bad_mode_fallback': 0, 'ok': 0}
        kept_pool = []
        for t in pool:
            sd = str(t[FI['signal_date']] or '')
            base, reason = self.s06_base_for_date(sd)
            stat_mode[reason] += 1
            if reason in ('no_row',):
                pass_t = True
            else:
                self.cur_keys = BASE_KEYS[base]
                pass_t = self.passes_fade(t)
            if pass_t:
                kept_pool.append(t)
        # 每日池 K=1
        by_date = {}
        for t in kept_pool:
            by_date.setdefault(str(t[FI['signal_date']]), []).append(t)
        final = []
        for sd, rows in by_date.items():
            rows.sort(key=lambda t: (-(t[FI['track_score']] if t[FI['track_score']] is not None else -1),
                                     RATING_RANK.get(t[FI['rating']] or '', 3),
                                     SIG_RANK.get(t[FI['signal']] or '', 9),
                                     t[FI['buy_date']]))
            final.append(rows[0])
        # 找 final 基笔在 quadrants A/K 里的记录
        base_key = lambda t: '|'.join([
            str(t[FI['signal_date']] or ''), str(t[FI['index_id']] or ''),
            str(t[FI['signal']] or ''), str(t[FI['buy_date']] or ''), str(t[FI['etf_code']] or '')])
        final_keys = {base_key(t) for t in final}
        out = {}
        for mk in ('A', 'K'):
            rows = []
            for rk in ['rating_high', 'rating_mid', 'rating_low']:
                for t in self.quads[rk][mk]:
                    if base_key(t) in final_keys:
                        rows.append(t)
            n, tp, mx, rmh = self.calc_stats(rows)
            out[mk] = {'n': n, 'tp': round(tp, 2), 'maxCC': mx, 'rmh': round(rmh, 2)}
        out['pool_n'] = len(pool)
        out['kept_pool_n'] = len(kept_pool)
        out['stat_mode'] = stat_mode
        return out

    def calc_stats(self, rows, use_fixed=False):
        FI = self.FI
        n = len(rows)
        tp = sum((r[FI['profit']] if use_fixed else self.recompute_profit(r)) for r in rows)
        deltas = {}
        dset = set()
        for r in rows:
            bd = str(r[FI['buy_date']])
            sd = str(r[FI['sell_date']] or '') or '99999999'
            deltas.setdefault(bd, [0, 0])
            deltas[bd][0] += self.buy_amount
            deltas.setdefault(sd, [0, 0])
            deltas[sd][1] += self.buy_amount
            dset.add(bd)
            dset.add(sd)
        cur = 0
        mx = 0
        for k in sorted(dset):
            cur -= deltas[k][1]
            cur += deltas[k][0]
            if cur > mx:
                mx = cur
        return n, tp, mx, (tp / mx * 100 if mx else 0)


def main():
    ap = argparse.ArgumentParser(description='A/B 双口径前端同构复刻(全信号表口径)')
    ap.add_argument('--trades-json', action='append', required=True,
                    help='signal_kelly_trades.json 路径(可传多次, 与 --label 一一对应)')
    ap.add_argument('--label', action='append',
                    help='每个 trades 文件的标签(如 A/B), 与 --trades-json 一一对应')
    ap.add_argument('--s06-json', default=DEFAULT_S06, help='kelly_mode_s06_state.json 路径')
    ap.add_argument('--features-json', default=DEFAULT_FEATURES,
                    help='kelly_loss_features.json 路径(默认项目内)')
    ap.add_argument('--buy-amount', type=float, default=10000.0,
                    help='每日资金池总额(默认 10000 = K1 每日池单笔保留时每笔=10000/1)')
    ap.add_argument('--fee-preset', default='etf_def', choices=list(FEE_PRESETS.keys()),
                    help='费率档(默认 etf_def=万3/最低5, 与前端默认/页面口径一致)')
    ap.add_argument('--json', action='store_true', help='输出机器可读 JSON 汇总')
    args = ap.parse_args()

    labels = args.label or [f'档{i}' for i in range(len(args.trades_json))]
    fee = FEE_PRESETS[args.fee_preset]
    results = {}
    for path, label in zip(args.trades_json, labels):
        r = _CaliberRunner(path, args.s06_json, args.features_json, args.buy_amount, fee)
        meta = {'generated_at': r.d.get('generated_at')}
        sigs = set()
        for qk, mv in r.quads.items():
            for mk, arr in mv.items():
                for t in arr:
                    sigs.add(str(t[r.FI['signal_date']] or ''))
        meta['signal_date_min'], meta['signal_date_max'] = min(sigs), max(sigs)
        meta['rating_high_A_n'] = len(r.quads.get('rating_high', {}).get('A', []))
        res = r.run_caliber('A')
        res['meta'] = meta
        results[label] = res
        if not args.json:
            print(f"== {label} ==")
            for k, v in meta.items():
                print(f"  {k}: {v}")
            print(f"  三区并集A: {res['pool_n']} -> S06过滤后: {res['kept_pool_n']} -> 每日池K1: {res['A']['n']}")
            for mk in ('A', 'K'):
                v = res[mk]
                print(f"  {mk}: n={v['n']} tp={v['tp']:.2f} maxCC={v['maxCC']:.0f} rmh={v['rmh']:.2f}%")
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()