# -*- coding: utf-8 -*-
"""mine28 状态自适应模式轮动(AUTO)存在性验证(mine28_regime_rotation,2026-08-23 主控令)。
目的: 验证「市场状态→七方案(P0_8键/P1_9键/A_on9/B_on9/C_on9/NEW_14键/NEW2_18键)」规则化切换器
      能否稳定跑赢最优单模式(NEW 全史 +122,648,mine24_compare 权威锚点)。
方法(§5.1 穷举最大化 + 防前视红线 §3.1):
  ①条件前瞻收益矩阵(用户点名核心): 每个候选状态信号触发后未来 20/60 交易日窗口内七方案各自
    收益/窗内MDD/胜率分布+平均排名(选段算规则、全史表仅描述性);
  ②结构穷举 {二态,三态}×{daily,weekly,monthly,event}×映射 7^k 全枚举(选段 2011-2020 内评估);
  ③样本外: 选段找规则冻结 → 验段 2021-2026 验证 + 3 组滚动邻段;
  ④切换成本双口径: natural 自然过渡(主口径) / forced 强制平仓重开(平仓价=买卖价线性插值近似估值,诚实标注);
  ⑤对照上限: 日/月/年事后最优 oracle(前视标注,仅天花板参考);大熊市专项(2021 后窗口)。
防前视三机检: ①分位特征仅用 mine10 滚动756日 trailing 分位,新增阈值全部固定常数/符号判断(注册表声明式审计);
  ②特征库逐特征核查(mine10_features.py 实读,trailing 结论进 feature_audit);
  ③时点穿越测试 T∈{20180629,20240208,20251231} 截断重算状态序列与全量逐位一致(assert)。
输入: static-site/data/signal_kelly_trades.json + docs/.../data/mine10_features.json +
      static-site/data/index/{hs300,sh}-all.json + data/mine24_global_search.json + data/mine24_compare.json。
输出: data/mine28_regime_rotation.json
复现: cd /Users/linhuichen/code/trade/docs/kelly/analysis/scripts/sim_window_loss_mining_20260822 && python3 mine28_regime_rotation.py
"""
import os, sys, json, datetime, itertools, bisect, statistics
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import (load, build_mode_pool, passes_fade, active_month_mask,
                      DEFAULT_FILTERS, calc_row, base_key, buy_with_fees, sell_with_fees, FP_DEF, PRIN)
from mine18_detail import FEATS_PATH, BEARS
from mine21_bigtour import build_rules
from mine22_joint import build_r2
from mine24_compare import A_SUB, B_SUB, C_SUB, NEW_KEYS, NEW2_KEYS

OUT_PATH = os.path.join(BASE, 'data', 'mine28_regime_rotation.json')
ROOT = R._ROOT
SEL_SEG = ('20110101', '20201231')
VAL_SEG = ('20210101', '20261231')
SCHEMES = ['P0', 'P1', 'A', 'B', 'C', 'NEW', 'NEW2']
SNAME = {'P0': 'P0_8键', 'P1': 'P1_9键', 'A': 'A_on9', 'B': 'B_on9', 'C': 'C_on9',
         'NEW': 'NEW_14键', 'NEW2': 'NEW2_18键'}

# ============================================================
# [1] 七方案重建 + 锚点断言(mine24_compare 同构)
# ============================================================
def build_schemes():
    feats = json.load(open(FEATS_PATH))
    tr, fIdx = load(ROOT + '/static-site/data/signal_kelly_trades.json')
    rows, fIdxP = R.prepare_rows()
    assert len(fIdxP) == len(fIdx)
    rules = build_rules(feats, fIdx); rules.update(build_r2(fIdx))
    c1 = lambda t: (t[2] in ('buy_aux', 'buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')
    h = {c: {R.base_key(t, fIdx) for t in rows if rules[c](t)} for c in set(A_SUB + B_SUB + C_SUB)}
    hc1 = {R.base_key(t, fIdx) for t in rows if c1(t)}
    g = {}
    for t in rows:
        g.setdefault(str(t[0]), []).append((R.base_key(t, fIdx), t))
    for sd in g: g[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])

    def ev(blk):
        sel = []
        for sd in sorted(g):
            for key, t in g[sd]:
                if key not in blk:
                    sel.append(t); break
        return sel

    sels = {}
    sels['P0'] = ev(set())
    sels['P1'] = ev(hc1)
    sels['A'] = ev(hc1 | set().union(*(h[c] for c in A_SUB)))
    sels['B'] = ev(hc1 | set().union(*(h[c] for c in B_SUB)))
    sels['C'] = ev(hc1 | set().union(*(h[c] for c in C_SUB)))

    pool = build_mode_pool(tr, fIdx, 'A')
    mD, eD, rD = len(fIdx), len(fIdx) + 1, len(fIdx) + 2
    R.IDX_PNL, R.IDX_SKEY = len(fIdx) + 3, len(fIdx) + 4
    RR = {'high': 0, 'mid': 1, 'low': 2}; SR = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    for t in pool:
        t.append(calc_row(t, fIdx))
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None, '') else float('inf')
        t.append((-ts, RR.get(str(t[fIdx['rating']] or ''), 3), SR.get(str(t[fIdx['signal']] or ''), 9),
                  str(t[fIdx['buy_date']] or '')))
    hist_keys = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']
    D8K = ['n2NovSpecialIndustry', 'excludeSpecialBear', 'janMidRating', 'janMidSpecial',
           'k2c5HkChase', 'r7MayReinforced', 'excludeAuxCross', 'greedy15']
    HITS = {}
    for c in sorted(set(D8K) | set(NEW_KEYS) | set(NEW2_KEYS)):
        if c in hist_keys:
            f = {kk: False for kk in DEFAULT_FILTERS}; f[c] = True
            HITS[c] = {base_key(t, fIdx) for t in pool if not passes_fade(t, fIdx, f, active_month_mask(f), mD, eD, rD)}
        else:
            HITS[c] = {base_key(t, fIdx) for t in pool if rules[c](t)}
    gp = {}
    for t in pool:
        gp.setdefault(str(t[0]), []).append((base_key(t, fIdx), t))
    for sd in gp: gp[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
    def ev_new(keys):
        blk = set()
        for c in keys: blk |= HITS[c]
        sel = []
        for sd in sorted(gp):
            for key, t in gp[sd]:
                if key not in blk:
                    sel.append(t); break
        return sel
    sels['NEW'] = ev_new(NEW_KEYS)
    sels['NEW2'] = ev_new(NEW2_KEYS)

    anchor = json.load(open(os.path.join(BASE, 'data', 'mine24_compare.json')))['anchor']
    exp = {'P0': anchor['p0'], 'P1': anchor['p1'], 'A': 119109.53, 'B': 109571.60, 'C': 107113.48,
           'NEW': anchor['new_net'], 'NEW2': anchor['new2_net']}
    got = {m: R.stats_of(sels[m])['total'] for m in SCHEMES}
    for m in SCHEMES:
        assert abs(got[m] - exp[m]) < 1.0, ('anchor FAIL', m, got[m], exp[m])
    print('锚点 PASS:', {SNAME[m]: round(v, 2) for m, v in got.items()})

    def blk_of(keys, extra=None):
        b = set(extra or ())
        for c in keys: b |= HITS[c]
        return b
    blks = {'P0': set(), 'P1': hc1,
            'A': hc1 | set().union(*(h[c] for c in A_SUB)),
            'B': hc1 | set().union(*(h[c] for c in B_SUB)),
            'C': hc1 | set().union(*(h[c] for c in C_SUB)),
            'NEW': blk_of(NEW_KEYS), 'NEW2': blk_of(NEW2_KEYS)}
    top1 = {}
    for m, src in (('P0', g), ('P1', g), ('A', g), ('B', g), ('C', g), ('NEW', gp), ('NEW2', gp)):
        blk = blks[m]; mm = {}
        for sd, lst in src.items():
            for key, t in lst:
                if key not in blk:
                    mm[sd] = t; break
        top1[m] = mm
        assert {base_key(t, fIdx) for t in sels[m]} == {base_key(t, fIdx) for t in mm.values()}, m
    return sels, top1, dict(fIdx=fIdx, generated_at=tr.get('generated_at'))

# ============================================================
# [2] 状态库(纯历史构造)+ 因子注册表
# ============================================================
def _ma_series(closes, w):
    out = [None] * len(closes)
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= w: s -= closes[i - w]
        if i >= w - 1: out[i] = s / w
    return out

def build_state_inputs(cutoff=None):
    raw = json.load(open(FEATS_PATH))
    keep = ['ma_bull', 'nhnl52', 'qvix_pct', 'div_pct', 'feargreed',
            'sent_hs300', 'h_dd252', 'h_vol20', 'h_ret20', 'h_slope20', 'rot10', 'north_d20']
    F = {}
    for k in keep:
        F[k] = {dt: v for dt, v in raw[k].items() if cutoff is None or dt <= cutoff}
    ohlc = json.load(open(ROOT + '/static-site/data/index/hs300-all.json'))['ohlc']
    ds = [o['date'] for o in ohlc]; cs = [o['close'] for o in ohlc]
    m20 = _ma_series(cs, 20); m60 = _ma_series(cs, 60); m120 = _ma_series(cs, 120); m200 = _ma_series(cs, 200)
    tier4 = {}; bull_run = {}; bear_drop = {}; ma60bull = {}
    for i in range(len(ds)):
        dt = ds[i]
        if cutoff and dt > cutoff: continue
        if m200[i] is None or m120[i] is None: continue
        c = cs[i]
        bull = m20[i] > m60[i] > m120[i]; bear = m20[i] < m60[i] < m120[i]
        if c > m200[i] and bull: t = '牛市·主升'
        elif c > m200[i]: t = '上升期'
        elif c < m200[i] and bear: t = '熊市·主跌'
        else: t = '下降期'
        tier4[dt] = t
        bull_run[dt] = 1 if t == '牛市·主升' else 0
        bear_drop[dt] = 1 if t == '熊市·主跌' else 0
        ma60bull[dt] = 1 if c > m60[i] else 0
    F['tier_bull'], F['tier_bear'], F['hs_ma60bull'], F['tier4'] = bull_run, bear_drop, ma60bull, tier4
    ohlc_sh = json.load(open(ROOT + '/static-site/data/index/sh-all.json'))['ohlc']
    dsh = [o['date'] for o in ohlc_sh]; csh = [o['close'] for o in ohlc_sh]
    sm200 = _ma_series(csh, 200); sm60 = _ma_series(csh, 60)
    a200 = {}; a60 = {}
    for i in range(len(dsh)):
        dt = dsh[i]
        if cutoff and dt > cutoff: continue
        if sm200[i] is not None: a200[dt] = 1 if csh[i] > sm200[i] else 0
        if sm60[i] is not None: a60[dt] = 1 if csh[i] > sm60[i] else 0
    F['sh_ma200bull'], F['sh_ma60bull'] = a200, a60
    return F

def factor_registry():
    reg = {}
    def lv(key, cmp_, th, desc, prov):
        def fn(F, d, key=key, cmp_=cmp_, th=th):
            v = F[key].get(d)
            if v is None: return False
            if cmp_ == 'ge': return v >= th
            if cmp_ == 'le': return v <= th
            if cmp_ == 'gt': return v > th
            if cmp_ == 'lt': return v < th
            if cmp_ == 'eq': return v == th
            return False
        rk = f"{key}{cmp_}{th}"
        reg[rk] = (fn, desc, prov)
        return rk
    f_bull = lv('tier_bull', 'eq', 1, '沪深300生产四档=牛市·主升(close>MA200且MA20>MA60>MA120)', '生产第9键判定源同款,无自由阈值')
    f_bear = lv('tier_bear', 'eq', 1, '沪深300四档=熊市·主跌(close<MA200且MA20<MA60<MA120)', '生产判定源同款')
    f_m60 = lv('hs_ma60bull', 'eq', 1, '沪深300 close>MA60', '固定均线,无分位')
    f_s200 = lv('sh_ma200bull', 'eq', 1, '上证 close>MA200', '固定均线')
    f_s60 = lv('sh_ma60bull', 'eq', 1, '上证 close>MA60', '固定均线')
    f_mb3 = lv('ma_bull', 'ge', 3, '8指数多头排列数>=3', '固定常数')
    f_mb0 = lv('ma_bull', 'le', 0, '8指数多头排列数=0(空头环境)', '固定常数')
    f_nh = lv('nhnl52', 'gt', 0, '52周净新高-新低>0', '符号判断')
    f_qlo = lv('qvix_pct', 'lt', 30, 'QVIX 滚动756日分位<30(波动冰点)', '滚动trailing分位✓+常数阈')
    f_qhi = lv('qvix_pct', 'gt', 70, 'QVIX 滚动756日分位>70(高波)', '滚动trailing分位✓+常数阈')
    f_fhi = lv('feargreed', 'ge', 60, '恐贪>=60', '固定常数')
    f_flo = lv('feargreed', 'le', 35, '恐贪<=35', '固定常数')
    f_shi = lv('sent_hs300', 'ge', 60, '沪深300情绪>=60', '固定常数')
    f_ddp = lv('h_dd252', 'lt', -15, '距250日高回撤超15%', '固定常数')
    f_r20 = lv('h_ret20', 'gt', 0, '沪深300 20日涨幅>0', '符号判断')
    f_sl20 = lv('h_slope20', 'gt', 0, 'MA20 斜率>0', '符号判断')
    f_dvp = lv('div_pct', 'ge', 70, '股息率滚动756日分位>=70(便宜)', '滚动trailing分位✓+常数阈')
    f_rot = lv('rot10', 'lt', 85, '10日轮动强度<85(缩圈)', '固定常数(全史p10≈77.8)')
    f_v25 = lv('h_vol20', 'gt', 25, '20日年化波动>25%', '固定常数=mine21 V2 同款')
    f_nth = lv('north_d20', 'gt', 0, '北向20日净流入>0(20141215起有数据)', '符号判断,缺失=False')
    trend5 = [f_bull, f_m60, f_s200, f_mb3, f_r20]
    risk5 = [f_qhi, f_v25, f_ddp, f_flo, f_rot]
    return reg, trend5, risk5

def make_pf(kind, spec, reg):
    """bin2: spec=factor key → 状态1=真/0=假;pair3: spec=(P,Q) → 0=P&¬Q(进攻牛)/1=P&Q(谨慎牛)/2=¬P(防守)。"""
    if kind == 'bin2':
        fn = reg[spec][0]
        return lambda F, d: 1 if fn(F, d) else 0, 2
    fp = reg[spec[0]][0]; fq = reg[spec[1]][0]
    def pf(F, d):
        if not fp(F, d): return 2
        return 1 if fq(F, d) else 0
    return pf, 3

def eff_states(pf, F, cal, freq):
    """返回每天生效的状态数组(None=未知): t 收盘出信号 t+1 生效。"""
    n = len(cal)
    raw = [pf(F, d) if F['tier4'].get(d) is not None else None for d in cal]
    if freq == 'event':
        out = [None] * n
        cur = None; pend = None; last = None
        for i in range(n):
            st = raw[i]
            if st is not None:
                if last is not None and st != last:
                    pend = st          # 今日翻转 → 明日生效
                last = st
            if pend is not None:
                cur = pend; pend = None
            elif cur is None and st is not None:
                cur = st
            out[i] = cur
        return out
    if freq == 'daily':
        return [None] + raw[:-1]
    # weekly / monthly: 采样点=上一周/上一月最后一个交易日
    def period_key(d, weekly):
        dt = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:]))
        if weekly:
            iso = dt.isocalendar(); return (iso[0], iso[1])
        return d[:6]
    last_idx = {}
    for i, d in enumerate(cal):
        last_idx[period_key(d, freq == 'weekly')] = i
    dec = [-1] * n
    prev_pk = None; prev_last = -1
    for i, d in enumerate(cal):
        pk = period_key(d, freq == 'weekly')
        if pk != prev_pk:
            if prev_pk is not None:
                prev_last = last_idx[prev_pk]
            prev_pk = pk
        dec[i] = prev_last
    return [raw[j] if j >= 0 else None for j in dec]

# ============================================================
# [3] 轮动模拟引擎(natural / forced 双口径;静态方案=常数方案数组特例)
# ============================================================
def simulate(scheme_arr, cal, top1, seg, cost='natural'):
    d1, d2 = seg
    by_sell = {}; by_year = {}; by_month = {}
    total = 0.0; ntr = 0; wins = 0
    open_pos = []; peak_pos = 0; switches = 0
    act_prev = None
    def settle(p, amt, mdd_date):
        nonlocal total, ntr, wins
        by_sell[mdd_date] = by_sell.get(mdd_date, 0.0) + amt
        by_month[p['sd'][:6]] = by_month.get(p['sd'][:6], 0.0) + amt
        by_year[p['sd'][:4]] = by_year.get(p['sd'][:4], 0.0) + amt
        total += amt; ntr += 1
        if amt > 0: wins += 1
    for i, d in enumerate(cal):
        if d < d1 or d > d2: continue
        act = scheme_arr[i]
        mat = [p for p in open_pos if p['ed'] <= d]
        if mat:
            for p in mat: settle(p, p['pnl_final'], p['ed'])
            open_pos = [p for p in open_pos if p['ed'] > d]
        if act_prev is not None and act != act_prev and cost == 'forced':
            for p in open_pos:
                bd, ed = p['bd'], p['ed']
                try:
                    dd_ed = datetime.date(int(ed[:4]), int(ed[4:6]), int(ed[6:])) if ed != '99991231' else None
                    denom = max((dd_ed - datetime.date(int(bd[:4]), int(bd[4:6]), int(bd[6:]))).days, 1) if dd_ed else 30
                    fr = min(max((datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])) -
                                  datetime.date(int(bd[:4]), int(bd[4:6]), int(bd[6:]))).days / denom, 0.0), 1.0)
                except Exception:
                    fr = 0.5
                px_in = p['bp'] * (1 + FP_DEF['slippage'])
                px_out = p['exitref'] * (1 - FP_DEF['slippage'])
                est = px_in + (px_out - px_in) * fr
                sr = sell_with_fees(p['shares_n'], est, p['code'], FP_DEF)
                settle(p, sr['net'] - PRIN - p['buy_fee'], d)
            open_pos = []
        if act != act_prev: switches += 1
        act_prev = act
        t = top1[act].get(d)
        if t:
            pnlD = t[R.IDX_PNL]
            sl = str(t[fIdxG['sell_date']] or '')
            ed = sl[:8] if sl else '99991231'
            bp = float(t[fIdxG['buy_price']] or 0)
            br = buy_with_fees(PRIN, bp, t[fIdxG['etf_code']] or '', FP_DEF)
            sp = float(t[fIdxG['sell_price']] or 0)
            if sp <= 0: sp = float(t[fIdxG['current_price']] or 0)
            open_pos.append(dict(sd=str(t[0]), bd=str(t[fIdxG['buy_date']])[:8], ed=ed, bp=bp, exitref=sp,
                                 code=t[fIdxG['etf_code']] or '', shares_n=br['shares'],
                                 buy_fee=br['commission'] + br['transferFee'], pnl_final=pnlD['pnlYuan']))
        if len(open_pos) > peak_pos: peak_pos = len(open_pos)
    for p in open_pos: settle(p, p['pnl_final'], p['ed'])
    cum = peak = 0.0; mdd = 0.0; trough = None
    for k2 in sorted(by_sell):
        cum += by_sell[k2]
        if cum > peak: peak = cum
        if cum - peak < mdd: mdd = cum - peak; trough = k2
    span = month_span(sorted(k for k in by_month)) if by_month else 1
    yrs = sorted(by_year)
    return dict(total=round(total, 2), n=ntr, win_rate=round(wins / max(ntr, 1) * 100, 1),
                mdd=round(mdd, 2), trough=trough,
                years_pos=sum(1 for v in by_year.values() if v > 0),
                years_neg=sum(1 for v in by_year.values() if v < 0),
                yearly={y: round(v, 2) for y, v in sorted(by_year.items())},
                monthly={k: round(v, 2) for k, v in sorted(by_month.items())},
                pos_month_share=round(sum(1 for v in by_month.values() if v > 0) / max(span, 1), 3),
                worst_month=round(min(by_month.values()), 2) if by_month else 0.0,
                zero_months=sum(1 for v in by_month.values() if abs(v) < 1e-9),
                peak_pos=peak_pos, switches=max(switches - 1, 0),
                switches_per_yr=round(max(switches - 1, 0) / max(year_count(seg), 1), 2))

def year_count(seg): return max(int(seg[1][:4]) - int(seg[0][:4]) + 1, 1)
def month_span(months):
    if not months: return 1
    a, b = months[0], months[-1]
    return max((int(b[:4]) - int(a[:4])) * 12 + (int(b[4:6]) - int(a[4:6])) + 1, 1)

# ============================================================
# [4] 条件前瞻收益矩阵
# ============================================================
def forward_matrix(top1, cal, F, reg, factors, seg, Ws=(20, 60)):
    d1, d2 = seg
    sdset = {d for d in top1['P0'] if d1 <= d <= d2}
    out = {}
    for fk in factors:
        fn, desc, prov = reg[fk]
        prev = None; trig = []
        for d in cal:
            if d1 <= d <= d2:
                cur = bool(fn(F, d))
                if cur and prev is False: trig.append(d)
                prev = cur
            elif d > d2:
                break
        out[fk] = {'desc': desc, 'prov': prov, 'triggers_sel': len(trig)}
        for W in Ws:
            acc = {m: dict(pnls=[], mdds=[], ranks=[], ns=[]) for m in SCHEMES}
            for td in trig:
                ti = CAL_IDX.get(td)
                if ti is None: continue
                win_days = set(cal[ti + 1: ti + 1 + W]) & sdset
                vals = {}
                for m in SCHEMES:
                    xs = []
                    bysell = {}
                    for sd in win_days:
                        t = top1[m].get(sd)
                        if t:
                            v = t[R.IDX_PNL]['pnlYuan']; xs.append(v)
                            sl = str(t[fIdxG['sell_date']] or '99991231')
                            bysell[sl[:8]] = bysell.get(sl[:8], 0.0) + v
                    tot = sum(xs)
                    cum = peak = 0.0; md = 0.0
                    for k2 in sorted(bysell):
                        cum += bysell[k2]
                        if cum > peak: peak = cum
                        if cum - peak < md: md = cum - peak
                    vals[m] = (tot, len(xs), md)
                order = sorted(SCHEMES, key=lambda m: -vals[m][0])
                rank = {m: i + 1 for i, m in enumerate(order)}
                for m in SCHEMES:
                    tot, n_, md = vals[m]
                    acc[m]['pnls'].append(tot); acc[m]['ns'].append(n_)
                    acc[m]['mdds'].append(md); acc[m]['ranks'].append(rank[m])
            sch = {}
            for m in SCHEMES:
                a = acc[m]; L = max(len(a['pnls']), 1)
                sch[m] = dict(mean_pnl=round(sum(a['pnls']) / L, 1),
                              pos_share=round(sum(1 for x in a['pnls'] if x > 0) / L, 3),
                              avg_rank=round(sum(a['ranks']) / L, 2),
                              mean_mdd=round(sum(a['mdds']) / L, 1),
                              mean_n=round(sum(a['ns']) / L, 1))
            out[fk][str(W)] = dict(triggers=len(trig), scheme=sch)
    return out

# ============================================================
# [5] 综合排名(mine26 §ranking 同方法学)
# ============================================================
def composite_rank(names, md_map):
    tot = {m: md_map[m]['total'] for m in names}
    def stab_key(m):
        md = md_map[m]
        vals = list(md.get('monthly', {}).values()) or [0.0]
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        wm = md.get('worst_month', min(vals))
        return (-md.get('pos_month_share', 0.0), wm, sd)
    go = sorted(names, key=lambda m: -tot[m])
    so = sorted(names, key=stab_key)
    gr = {m: i + 1 for i, m in enumerate(go)}
    sr = {m: i + 1 for i, m in enumerate(so)}
    return {m: dict(gain=gr[m], stab=sr[m], sum=gr[m] + sr[m]) for m in names}

# ============================================================
# main
# ============================================================
FIDX_G = None
fIdxG = None
CAL_IDX = {}

def main():
    global FIDX_G, fIdxG, CAL_IDX
    t0 = datetime.datetime.now()
    sels, top1, meta = build_schemes()
    FIDX_G = meta['fIdx']; fIdxG = meta['fIdx']

    F = build_state_inputs()
    ohlc = json.load(open(ROOT + '/static-site/data/index/hs300-all.json'))['ohlc']
    cal = [o['date'] for o in ohlc]
    CAL_IDX = {d: i for i, d in enumerate(cal)}
    reg, trend5, risk5 = factor_registry()

    # ---- 机检③ 时点穿越 ----
    tt = {}
    for T in ('20180629', '20240208', '20251231'):
        Fc = build_state_inputs(cutoff=T)
        ok = True; bad = None
        for fk, (fn, _, _) in reg.items():
            a = [fn(F, d) for d in cal if d <= T]
            b = [fn(Fc, d) for d in cal if d <= T]
            if a != b: ok = False; bad = fk; break
        if ok:
            a = [F['tier4'].get(d) for d in cal if d <= T]
            b = [Fc['tier4'].get(d) for d in cal if d <= T]
            if a != b: ok = False; bad = 'tier4'
        tt[T] = dict(pass_=ok, bad_factor=bad)
        print(f"机检③时点穿越 T={T}: {'PASS 逐位一致' if ok else 'FAIL @' + str(bad)}")
        assert ok

    quantile_audit = [
        dict(item='分位特征(qvix_pct/div_pct)', verdict='PASS-trailing',
             note='仅用 mine10 rolling_pctile(756) 滚动分位(含当日不含未来,mine10_features.py L84-99 实读核查);本次新增阈值全部为固定常数或符号判断,零全期分位'),
        dict(item='方案定义层历史规则阈值(mine21 qth() 全期分位:N1/T1/D1/Q1/S2/V3/AD1 等)', verdict='DISCLOSED-legacy',
             note='属七方案自身历史固化定义(mine24 权威锚点组成部分),非本次新建信号;原样保留保锚点一致,在此如实披露'),
    ]
    feature_audit = [
        dict(feature='tier4/tier_bull/tier_bear(hs300 四档)', construction='close vs MA200 且 MA20>MA60>MA120(queries.py L552-594 生产同款自算)', trailing=True, verdict='PASS'),
        dict(feature='hs_ma60bull/sh_ma200bull/sh_ma60bull', construction='固定窗口滚动均线', trailing=True, verdict='PASS'),
        dict(feature='ma_bull/nhnl52/rot10/feargreed/sent_hs300/h_dd252/h_vol20/h_ret20/h_slope20', construction='daily_metric 直读或 trailing 窗口衍生(dd252 过去251~当日/vol20 近19~当日/slope20 均线对均线,均截至当日)', trailing=True, verdict='PASS'),
        dict(feature='qvix_pct/div_pct', construction='滚动756交易日分位', trailing=True, verdict='PASS(滚动分位合规)'),
        dict(feature='north_d20', construction='年内累计−20日前累计', trailing=True, verdict='PASS(覆盖20141215起,缺失按False保守)'),
        dict(feature='turn_pct/margin_chg20/adline_gap 等 2016+/2021+ 覆盖特征', construction='覆盖不足全史', trailing=True, verdict='EXCLUDED 未入状态库'),
        dict(feature='方案定义层 qth() 全期分位阈值', construction='全样本分位定阈', trailing=False, verdict='DISCLOSED 七方案历史固化产物非本次信号'),
    ]

    # ================= 条件前瞻矩阵 =================
    print('\n== 条件前瞻收益矩阵(触发=转真事件,T+1 生效,W=20/60 交易日) ==')
    fwd_sel = forward_matrix(top1, cal, F, reg, list(reg.keys()), SEL_SEG)
    fwd_all = forward_matrix(top1, cal, F, reg, list(reg.keys()), ('00010101', '99991231'))
    print(f"factors={len(reg)}, 选段触发示例: " + ', '.join(f"{k}:{fwd_sel[k]['triggers_sel']}" for k in list(reg)[:6]))

    # 贪心映射(从前向表导出): 进攻态=平均排名最前;防守态=平均窗内MDD最浅;中间态=次优
    greedy = {}
    for fk in reg:
        sc = {m: (fwd_sel[fk]['20']['scheme'][m]['avg_rank'] + fwd_sel[fk]['60']['scheme'][m]['avg_rank']) / 2 for m in SCHEMES}
        dd = {m: (fwd_sel[fk]['20']['scheme'][m]['mean_mdd'] + fwd_sel[fk]['60']['scheme'][m]['mean_mdd']) / 2 for m in SCHEMES}
        best = min(SCHEMES, key=lambda m: sc[m])
        safest = min((m for m in SCHEMES if m != best), key=lambda m: dd[m])
        mid = min((m for m in SCHEMES if m not in (best, safest)), key=lambda m: sc[m])
        greedy[fk] = dict(bin2=[mid, best], pair3=[best, mid, safest],
                          scores={m: round(v, 2) for m, v in sc.items()}, mdd={m: round(v, 1) for m, v in dd.items()})

    # ================= 结构穷举(选段) =================
    print('\n== 结构穷举(选段 2011-2020)==')
    parts = [('bin2', fk) for fk in reg] + [('pair3', (p, q)) for p in trend5 for q in risk5]
    results = []
    stat_seg = {}
    for m in SCHEMES:
        arr = [m] * len(cal)
        stat_seg[m] = simulate(arr, cal, top1, SEL_SEG)
    for kind, spec in parts:
        pf, nst = make_pf(kind, spec, reg)
        for freq in ('daily', 'weekly', 'monthly', 'event'):
            est = eff_states(pf, F, cal, freq)
            base = [0 if x is None else x for x in est]
            for mapping in itertools.product(SCHEMES, repeat=nst):
                lut = list(mapping)
                arr = [lut[x] if est[i] is not None else 'NEW' for i, x in enumerate(base)]
                mt = simulate(arr, cal, top1, SEL_SEG)
                mt.pop('monthly'); mt.pop('yearly')
                results.append(dict(kind=kind, spec=list(spec) if isinstance(spec, tuple) and len(spec) == 2 else spec,
                                    nstate=nst, freq=freq, mapping=list(mapping), **mt))
        print(f'  {kind} {spec} done ({len(results)} cumulative) {datetime.datetime.now()-t0}')
    print(f'穷举组合总数={len(results)},耗时 {datetime.datetime.now()-t0}')

    cand_md = dict(stat_seg)
    for i, r in enumerate(results): cand_md[f'i{i}'] = r
    comp_sel = composite_rank(list(cand_md.keys()), cand_md)
    for i, r in enumerate(results): r['composite'] = comp_sel[f'i{i}']
    stat_comp_sel = {m: comp_sel[m] for m in SCHEMES}
    results.sort(key=lambda r: (r['composite']['sum'], -r['total']))

    # ================= 样本外验证(冻结规则 → 验段) =================
    print('\n== 样本外验证(选段冻结 → 2021-2026) ==')
    stat_val = {}
    for m in SCHEMES:
        arr = [m] * len(cal)
        stat_val[m] = simulate(arr, cal, top1, VAL_SEG)
    best_static_val = max(SCHEMES, key=lambda m: stat_val[m]['total'])

    priors = [
        ('PRIOR1_牛市主升切A_其余NEW', 'bin2', 'tier_bulleq1', ['NEW', 'A']),
        ('PRIOR2_牛市主升切A_其余C', 'bin2', 'tier_bulleq1', ['C', 'A']),
        ('PRIOR3_牛A_谨慎牛NEW_非牛C', 'pair3', ('tier_bulleq1', 'qvix_pctgt70'), ['A', 'NEW', 'C']),
        ('PRIOR4_牛市主升切A_其余B', 'bin2', 'tier_bulleq1', ['B', 'A']),
        ('PRIOR5_前向表贪心_tierBull二态', 'bin2', 'tier_bulleq1', greedy['tier_bulleq1']['bin2']),
        ('PRIOR6_上证MA200上A下C', 'bin2', 'sh_ma200bulleq1', ['C', 'A']),
        ('PRIOR7_多头排列3家以上A_否则NEW', 'bin2', 'ma_bullge3', ['NEW', 'A']),
    ]
    val_rows = []
    def eval_rule(kind, spec, mapping, freq):
        pf, nst = make_pf(kind, spec, reg)
        est = eff_states(pf, F, cal, freq)
        lut = list(mapping) + [mapping[-1]] * (nst - len(mapping))
        arr = [lut[x] if x is not None else 'NEW' for x in ([0 if v is None else v for v in est])]
        return simulate(arr, cal, top1, VAL_SEG)

    seen = set()
    for r in results[:60]:
        key = '|'.join(map(str, [r['kind'], r['spec'], r['mapping'], r['freq']]))
        if key in seen: continue
        seen.add(key)
        spec = tuple(r['spec']) if isinstance(r['spec'], list) else r['spec']
        mt = eval_rule(r['kind'], spec, r['mapping'], r['freq'])
        val_rows.append(dict(rule=key.split('|', 1)[1], kind=r['kind'],
                             spec=r['spec'] if not isinstance(spec, tuple) else list(spec),
                             mapping=r['mapping'], freq=r['freq'],
                             sel_total=r['total'], sel_mdd=r['mdd'], sel_comp=r['composite'],
                             **mt))
        if len(val_rows) >= 40: break
    for nm, kind, spec, mp in priors:
        mt = eval_rule(kind, spec, mp, 'daily')
        est = None
        pf, nst = make_pf(kind, spec, reg)
        e = eff_states(pf, F, cal, 'daily')
        arr = [(mp[x] if x is not None else 'NEW') for x in e]
        sel_mt = simulate(arr, cal, top1, SEL_SEG)
        val_rows.append(dict(rule=nm, kind=kind, spec=list(spec) if isinstance(spec, tuple) else spec,
                             mapping=list(mp), freq='daily', sel_total=sel_mt['total'], sel_mdd=sel_mt['mdd'], **mt))

    names_val = SCHEMES[:] + [f'r{i}' for i in range(len(val_rows))]
    md_val = dict(stat_val)
    for i, r in enumerate(val_rows): md_val[f'r{i}'] = r
    comp_val = composite_rank(names_val, md_val)
    for i, r in enumerate(val_rows): r['val_composite'] = comp_val[f'r{i}']
    stat_comp_val = {m: comp_val[m] for m in SCHEMES}

    bs = stat_val[best_static_val]
    verdicts = []
    for i, r in enumerate(val_rows):
        strict = bool(r['total'] > bs['total'] and r['mdd'] >= bs['mdd'] and r['years_pos'] >= bs['years_pos'])
        soft = bool(comp_val[f'r{i}']['sum'] < min(comp_val[m]['sum'] for m in SCHEMES))
        verdicts.append(dict(rule=r['rule'], net=r['total'], net_beats=bool(r['total'] > bs['total']),
                             mdd_not_worse=bool(r['mdd'] >= bs['mdd']), strict_pass=strict, soft_pass=soft))
    any_strict = any(v['strict_pass'] for v in verdicts)
    any_soft = any(v['soft_pass'] for v in verdicts)
    print(f"验段最优静态={SNAME[best_static_val]} net={bs['total']:+,.0f} mdd={bs['mdd']:,.0f}")
    for v in verdicts:
        if v['strict_pass'] or v['soft_pass']:
            print(f"  [{'STRICT' if v['strict_pass'] else 'soft'}] {v['rule']} net={v['net']:+,.0f}")

    # ---- 滚动邻段(top5 冻结规则) ----
    rolls = [('2015-2018', ('20150101', '20181231')), ('2018-2021', ('20180101', '20211231')), ('2021-2024', ('20210101', '20241231'))]
    roll_out = []
    for r in val_rows[:5]:
        rr = {'rule': r['rule']}
        pf, nst = make_pf(r['kind'], tuple(r['spec']) if isinstance(r['spec'], list) and len(r['spec']) == 2 else r['spec'], reg)
        for lab, sg in rolls:
            est = eff_states(pf, F, cal, r['freq'])
            lut = list(r['mapping'])
            arr = [lut[x] if x is not None else 'NEW' for x in est]
            mt = simulate(arr, cal, top1, sg)
            rr[lab] = dict(total=mt['total'], mdd=mt['mdd'], pos_month_share=mt['pos_month_share'])
        roll_out.append(rr)

    # ---- 敏感性: 剔除单月(验段,top5 规则+7静态) ----
    sens = {}
    def excl_tot(md_monthly, ex):
        return round(sum(v for k, v in md_monthly.items() if k not in ex), 2)
    EX = {'202604'}; EX2 = {'202604', '202512'}
    for r in val_rows[:5]:
        sens[r['rule']] = dict(full=r['total'], excl_202604=excl_tot(r['monthly'], EX), excl_202604_202512=excl_tot(r['monthly'], EX2))
    sens_static = {m: dict(full=stat_val[m]['total'], excl_202604=excl_tot(stat_val[m]['monthly'], EX),
                           excl_202604_202512=excl_tot(stat_val[m]['monthly'], EX2)) for m in SCHEMES}

    # ---- oracle 上限(前视标注) ----
    oracle = {}
    for lab, sg in (('sel_2011_2020', SEL_SEG), ('val_2021_2026', VAL_SEG)):
        d1, d2 = sg
        sds = [d for d in top1['P0'] if d1 <= d <= d2]
        daily = 0.0
        per_mon = {m: {} for m in SCHEMES}; per_yr = {m: {} for m in SCHEMES}
        for m in SCHEMES:
            for d in sds:
                t = top1[m].get(d)
                if t:
                    v = t[R.IDX_PNL]['pnlYuan']
                    per_mon[m][d[:6]] = per_mon[m].get(d[:6], 0.0) + v
                    per_yr[m][d[:4]] = per_yr[m].get(d[:4], 0.0) + v
        for d in sds:
            best = None
            for m in SCHEMES:
                t = top1[m].get(d)
                if t:
                    v = t[R.IDX_PNL]['pnlYuan']
                    best = v if best is None else max(best, v)
            if best is not None: daily += best
        months = sorted(set().union(*[set(v) for v in per_mon.values()]))
        years = sorted(set().union(*[set(v) for v in per_yr.values()]))
        oracle[lab] = dict(daily_best=round(daily, 2),
                           monthly_best=round(sum(max(per_mon[m].get(mo, 0.0) for m in SCHEMES) for mo in months), 2),
                           yearly_best=round(sum(max(per_yr[m].get(y, 0.0) for m in SCHEMES) for y in years), 2),
                           note='事后(前视)上限参考,不可上线')

    # ---- 大熊市专项(2021+) ----
    bears_out = {}
    for lab, a, b in BEARS:
        if a < '20210101': continue
        row = {}
        for m in SCHEMES:
            arr = [m] * len(cal)
            mt = simulate(arr, cal, top1, (max(a, '20210101'), min(b, '20261231')))
            row[SNAME[m]] = dict(total=mt['total'], mdd=mt['mdd'])
        bears_out[lab] = row

    # ---- forced 口径(strict-PASS 或 soft-PASS 的前 3 条规则) ----
    forced_out = []
    fcand = [r for r, v in zip(val_rows, verdicts) if v['strict_pass'] or v['soft_pass']][:3] or val_rows[:3]
    for r in fcand:
        pf, nst = make_pf(r['kind'], tuple(r['spec']) if isinstance(r['spec'], list) and len(r['spec']) == 2 else r['spec'], reg)
        est = eff_states(pf, F, cal, r['freq'])
        lut = list(r['mapping'])
        arr = [lut[x] if x is not None else 'NEW' for x in est]
        mt = simulate(arr, cal, top1, VAL_SEG, cost='forced')
        forced_out.append(dict(rule=r['rule'], forced=dict(total=mt['total'], mdd=mt['mdd'], switches=mt['switches']),
                               natural_total=r['total'],
                               note='平仓价=买入价(含滑点)至参考卖出价线性插值近似估值+卖出费率;近似口径诚实标注'))

    # ================= 条件优势画像(水平切分: signal_date 前一日状态真/假 两群的七方案表现) =================
    def cond_level_table(seg):
        d1, d2 = seg
        sds = [d for d in top1['P0'] if d1 <= d <= d2 and CAL_IDX.get(d) is not None and CAL_IDX[d] >= 1]
        tbl = {}
        for fk in reg:
            fn = reg[fk][0]
            grp = {True: {m: [0.0, 0, 0] for m in SCHEMES}, False: {m: [0.0, 0, 0] for m in SCHEMES}}
            ndays = {True: 0, False: 0}
            for sd in sds:
                st = bool(fn(F, cal[CAL_IDX[sd] - 1]))
                ndays[st] += 1
                for m in SCHEMES:
                    t = top1[m].get(sd)
                    if t:
                        v = t[R.IDX_PNL]['pnlYuan']
                        g = grp[st][m]; g[0] += v; g[1] += 1
                        if v > 0: g[2] += 1
            row = {}
            for st in (True, False):
                sch = {}
                for m in SCHEMES:
                    tot, n_, w_ = grp[st][m]
                    sch[m] = dict(total=round(tot, 1), n=n_, win_rate=round(w_ / max(n_, 1) * 100, 1),
                                  per_day=round(tot / max(ndays[st], 1), 2))
                rk = sorted(SCHEMES, key=lambda m: -sch[m]['per_day'])
                sch['_rank'] = {m: i + 1 for i, m in enumerate(rk)}
                sch['_days'] = ndays[st]
                row['真' if st else '假'] = sch
            tbl[fk] = dict(desc=reg[fk][1], split=row)
        return tbl
    cond_sel = cond_level_table(SEL_SEG)
    cond_val = cond_level_table(VAL_SEG)

    # ---- 四档/因子状态按年占比(判定源覆盖透明化) ----
    tier_year = {}
    for d, tv in F['tier4'].items():
        y = d[:4]
        tier_year.setdefault(y, {}); tier_year[y][tv] = tier_year[y].get(tv, 0) + 1

    # ---- 诊断性上限: 验段全枚举(in-sample cheating,前视标注,仅衡量天花板) ----
    print('\n== 验段全枚举(诊断性上限,前视标注)==')
    val_enum_best = None; val_enum_top = []
    for kind, spec in parts:
        pf, nst = make_pf(kind, spec, reg)
        for freq in ('daily', 'weekly', 'monthly', 'event'):
            est = eff_states(pf, F, cal, freq)
            base = [0 if x is None else x for x in est]
            for mapping in itertools.product(SCHEMES, repeat=nst):
                lut = list(mapping)
                arr = [lut[x] if est[i] is not None else 'NEW' for i, x in enumerate(base)]
                mt = simulate(arr, cal, top1, VAL_SEG)
                rec = dict(kind=kind, spec=list(spec) if isinstance(spec, tuple) and len(spec) == 2 else spec,
                           nstate=nst, freq=freq, mapping=list(mapping), total=mt['total'], mdd=mt['mdd'],
                           pos_month_share=mt['pos_month_share'], years_pos=mt['years_pos'])
                val_enum_top.append(rec)
                if val_enum_best is None or mt['total'] > val_enum_best['total']:
                    val_enum_best = rec
    val_enum_top.sort(key=lambda r: -r['total'])
    print(f"验段事后最优切换器(前视): net={val_enum_best['total']:+,.0f} {val_enum_best}")

    # ---- 滚动窗推导稳定性: 不同选段重导贪心规则是否同一 ----
    roll_deriv = {}
    for lab, sg in [('2011-2014', ('20110101', '20141231')), ('2014-2017', ('20140101', '20171231')),
                    ('2017-2020', ('20170101', '20201231')), ('全段2011-2020', SEL_SEG)]:
        fm = forward_matrix(top1, cal, F, reg, ['tier_bulleq1', 'sh_ma200bulleq1', 'ma_bullge3', 'h_ret20gt0'], sg)
        deriv = {}
        for fk in fm:
            sc = {m: (fm[fk]['20']['scheme'][m]['avg_rank'] + fm[fk]['60']['scheme'][m]['avg_rank']) / 2 for m in SCHEMES}
            best = min(SCHEMES, key=lambda m: sc[m])
            dd2 = {m: (fm[fk]['20']['scheme'][m]['mean_mdd'] + fm[fk]['60']['scheme'][m]['mean_mdd']) / 2 for m in SCHEMES}
            safest = min((m for m in SCHEMES if m != best), key=lambda m: dd2[m])
            deriv[fk] = dict(attack_best=best, defend_safest=safest,
                             scores={m: round(v, 2) for m, v in sc.items()})
        roll_deriv[lab] = deriv

    out = dict(
        generated_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        data_generated_at=meta['generated_at'],
        caliber=dict(base='current baseline v1.1.2, mode A + etf_def 费后 + K1 补位口径(mine24_compare 同构复刻)',
                     schemes=[SNAME[m] for m in SCHEMES], sel_seg=list(SEL_SEG), val_seg=list(VAL_SEG),
                     timing='t 日收盘出状态信号、t+1 交易日生效;weekly=上周末采样;monthly=上月末采样;event=翻转次日生效;状态缺失日默认不持新仓视角(等价新仓照开但方案=NEW 兜底,实际 2011 起无缺失)',
                     pass_criteria='STRICT=验段净利>最优静态 且 MDD 不更深 且 正年份不少于其;SOFT=双维综合分(收益名次+平稳名次)小于全部静态方案'),
        anchors={SNAME[m]: round(R.stats_of(sels[m])['total'], 2) for m in SCHEMES},
        lookahead_checks=dict(time_travel=tt, quantile_audit=quantile_audit, feature_audit=feature_audit),
        forward_matrix_sel=fwd_sel, forward_matrix_full=fwd_all,
        greedy_from_forward=greedy,
        static_sel_seg={m: {k: v for k, v in stat_seg[m].items() if k != 'monthly'} for m in SCHEMES},
        static_val_seg={m: {k: v for k, v in stat_val[m].items() if k != 'monthly'} for m in SCHEMES},
        static_comp_sel=stat_comp_sel, static_comp_val=stat_comp_val,
        search=dict(n_partitions=len(parts), n_combos=len(results),
                    top30=results[:30]),
        validation=dict(best_static=SNAME[best_static_val], rows=val_rows, verdicts=verdicts,
                        pass_strict_any=any_strict, pass_soft_any=any_soft),
        rolling_windows=roll_out,
        sensitivity_excl_single_month=dict(rules=sens, statics=sens_static),
        oracle_ceilings=oracle,
        conditional_level_sel=cond_sel, conditional_level_val=cond_val,
        tier4_days_by_year=tier_year,
        val_enumeration_oracle=dict(best=val_enum_best, top10=val_enum_top[:10],
                                    note='验段内直接全枚举=前视作弊上限,仅诊断过拟合幅度与理论天花板,不可上线'),
        rolling_derivation_stability=roll_deriv,
        bears_since2021=bears_out,
        forced_close_variant=forced_out,
    )
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('\nsaved ->', OUT_PATH)
    print('总耗时', datetime.datetime.now() - t0)
    print('\n== 验段静态基线 ==')
    for m in SCHEMES:
        sv = stat_val[m]
        print(f"  {SNAME[m]:12s} net={sv['total']:+10,.0f} mdd={sv['mdd']:>8,.0f} 正年{sv['years_pos']} 正月占{sv['pos_month_share']:.2f} 综合分{comp_val[m]['sum']}")
    print('\n== 切换器验证判决 ==')
    for v in verdicts:
        tag = 'STRICT-PASS' if v['strict_pass'] else ('SOFT-PASS' if v['soft_pass'] else 'FAIL')
        print(f"  [{tag}] {v['rule'][:70]:70s} net={v['net']:+10,.0f} beats_best_static={v['net_beats']}")

if __name__ == '__main__':
    main()
