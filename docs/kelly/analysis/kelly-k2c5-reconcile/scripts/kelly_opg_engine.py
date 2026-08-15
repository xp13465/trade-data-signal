# -*- coding: utf-8 -*-
"""凯利回测 v1.0.0 可操作口径复现引擎(口径补测, 2026-08-15)
目的: 修正 kelly-quadrant-loss-elimination.md 初版「裸 G」口径局限——用 v1.0.0 基准(AI宏4+3+1 + 每日池等分 + K=1
      + G 用 13万 P≤3d「先卖年轻仓」可操作口径)重测「亏损象限识别与剔除」结论, 并补 F 等其他卖出模式(9模式 A-I 全测)。
口径: 9模式可操作口径映射 =
      A-F: 每日池+top-K 裸(短持, 峰持仓≤20万天然可操作, 与初版一致)
      G:   P≤3d 13万 b0(超仓先卖持有≤3天年轻仓, 无年轻仓才卖最老, 强平记0利保守口径)  [v1.0.0 基准 G]
      H:   满仓不买@7万(手段A, 无强平 b0=b1)
      I:   满仓不买@15万(手段A)
      仿真内核与前端 lab.js _kellyAihlineP3dCap/_kellyAihlineHoldCap 逐位对齐(node 交叉验证: 13万 b0=+205,746/158.27%)。
输入: static-site/data/signal_kelly_trades.json (2026-08-15 02:38 批, G 基笔 7598)
依赖: kelly_engine.py(KellyEngine, 同目录)
输出: 9模式基线 + 用户4象限/候选键/最优组合剔除边际 + 按年分解 + fixed 对照(打印)
复现: python3 kelly_opg_engine.py
"""
import sys, os, datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO, BUY_AMOUNT

_P3_DAYS = 3
_CAL_RATIO = 1.498
MODES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']
OPG_STRATS = {'G': ('p3d', 130000, 'b0'), 'H': ('hold', 70000, None), 'I': ('hold', 150000, None)}

def _cal_span(bd, sd):
    """日历日差(对齐前端 _kellyAihlineCalSpan)"""
    if not bd or not sd or sd < bd: return 0
    d1 = datetime.date(int(bd[0:4]), int(bd[4:6]), int(bd[6:8]))
    d2 = datetime.date(int(sd[0:4]), int(sd[4:6]), int(sd[6:8]))
    return max(round((d2 - d1).days), 0)

def _realize(pr, rp, bd, sd, hd, amt, closeDate, model):
    """强平利润兑现(对齐前端 _kellyAihlineRealize): b0=0利保守 / b1=按持有时间线性"""
    ns = _cal_span(bd, sd) if sd else (hd * _CAL_RATIO if hd else 0)
    cs = _cal_span(bd, closeDate) if closeDate else ns
    if ns <= 0 or cs >= ns: return (pr, rp, hd)
    f = cs / ns
    if model == 'b0': return (0.0, 0.0, round(hd * f))
    if model == 'b1': return (pr * f, pr * f / amt * 100, round(hd * f))
    return (0.0, 0.0, 0)

def p3d_cap(trades, cap, model='b0'):
    """P≤3d「先卖年轻仓」仿真(对齐前端 _kellyAihlineP3dCap): 超cap先卖持有≤3天年轻仓(几笔中先卖买日最早),
    无年轻仓才FIFO卖最老。返回 (kept, peak)。node 交叉验证通过。"""
    trs = [dict(t, closed=None) for t in trades]
    buysByDate, allDates = {}, set()
    for t in trs:
        bd = t['buy_date']
        buysByDate.setdefault(bd, []).append(t)
        allDates.add(bd)
        if t['sell_date']: allDates.add(t['sell_date'])
    allDates = sorted(allDates)
    openTrs, kept, cur, peak = [], [], 0.0, 0.0
    for dt in allDates:
        newOpen = []
        for t in openTrs:
            if t['sell_date'] == dt and t['closed'] is None:
                t['closed'] = 'natural'; cur -= t['amount']
                kept.append(t)
            else: newOpen.append(t)
        openTrs = newOpen
        dayTrs = buysByDate.get(dt)
        if dayTrs:
            dayTotal = sum(t['amount'] for t in dayTrs)
            needed = cur + dayTotal - cap
            if needed > 1e-6:
                while needed > 1e-6 and openTrs:
                    sel, selBuy = None, None
                    for ot in openTrs:
                        if ot['closed'] is not None: continue
                        if _cal_span(ot['buy_date'], dt) <= _P3_DAYS:
                            if sel is None or ot['buy_date'] < selBuy: sel, selBuy = ot, ot['buy_date']
                    if sel is None:
                        sel = openTrs[0]
                        for ot2 in openTrs:
                            if ot2['closed'] is not None: continue
                            if sel is None or ot2['buy_date'] < sel['buy_date']: sel = ot2
                    r = _realize(sel['profit'], sel['return_pct'], sel['buy_date'], sel['sell_date'], sel['hold_days'], sel['amount'], dt, model)
                    kept.append({'profit': r[0], 'return_pct': r[1], 'buy_date': sel['buy_date'], 'sell_date': dt,
                                 'hold_days': r[2], 'amount': sel['amount'], 'fee_cost': sel['fee_cost']})
                    cur -= sel['amount']; sel['closed'] = 'p3d'
                    for i in range(len(openTrs) - 1, -1, -1):
                        if openTrs[i] is sel: openTrs.pop(i); break
                    needed = cur + dayTotal - cap
                if needed <= 1e-6:
                    openTrs.extend(dayTrs); cur += dayTotal
            else:
                openTrs.extend(dayTrs); cur += dayTotal
        if cur > peak: peak = cur
    for t in openTrs:
        if t['closed'] is None: kept.append(t)
    return kept, round(peak, 4)

def hold_cap(trades, cap):
    """手段A「满仓不买」仿真(对齐前端 _kellyAihlineHoldCap): 到cap停买, 当日超容整批跳过, 不强制平仓。返回 (kept, peak)。"""
    trs = [dict(t, closed=None) for t in trades]
    buysByDate, allDates = {}, set()
    for t in trs:
        bd = t['buy_date']
        buysByDate.setdefault(bd, []).append(t)
        allDates.add(bd)
        if t['sell_date']: allDates.add(t['sell_date'])
    allDates = sorted(allDates)
    openTrs, kept, cur, peak = [], [], 0.0, 0.0
    for dt in allDates:
        newOpen = []
        for t in openTrs:
            if t['sell_date'] == dt and t['closed'] is None:
                t['closed'] = 'natural'; cur -= t['amount']
                kept.append(t)
            else: newOpen.append(t)
        openTrs = newOpen
        dayTrs = buysByDate.get(dt)
        if dayTrs:
            dayTotal = sum(t['amount'] for t in dayTrs)
            if cur + dayTotal - cap <= 1e-6:
                openTrs.extend(dayTrs); cur += dayTotal
        if cur > peak: peak = cur
    for t in openTrs:
        if t['closed'] is None: kept.append(t)
    return kept, round(peak, 4)

class OpgEngine:
    """v1.0.0 可操作口径引擎: 9模式各自可操作口径统计 + 剔除边际"""
    def __init__(self, td):
        self.eng = KellyEngine(td)
        self.fi = self.eng.fIdx

    def _mode_recomputed(self, mode, filters, exclude_keys, fixed_amt=None):
        fi = self.fi
        arr = self.eng._all_by_mode[mode]
        pool = self.eng.collect_base_pool(filters, exclude_keys)
        kept = self.eng._kept_keys(pool, filters.get('positionCapK', 1)) if filters.get('positionCap') else None
        day_counts = self.eng._day_counts(kept) if kept else {}
        out = []
        for t in arr:
            if not self.eng.passes_fade(t, filters): continue
            if exclude_keys and self.eng.base_key(t) in exclude_keys: continue
            if kept is not None and self.eng.base_key(t) not in kept: continue
            if fixed_amt is not None:
                amt = fixed_amt
            else:
                amt = BUY_AMOUNT / day_counts.get(str(t[fi['signal_date']]), 1) if day_counts else BUY_AMOUNT
            p, rp, fee = self.eng.recompute(t, amt)
            out.append({'profit': p, 'return_pct': rp, 'fee_cost': fee,
                        'buy_date': str(t[fi['buy_date']] or ''), 'sell_date': str(t[fi['sell_date']] or ''),
                        'hold_days': t[fi['hold_days']] or 0, 'amount': amt})
        return out

    def opg_mode_stats(self, mode, recomputed):
        """单模式可操作口径 stats: 返回 (stats_dict, peak)。A-F裸 / G=P3d13万b0 / H=hold7万 / I=hold15万"""
        if mode in OPG_STRATS:
            kind, cap, model = OPG_STRATS[mode]
            kt, peak = p3d_cap(recomputed, cap, model) if kind == 'p3d' else hold_cap(recomputed, cap)
            tp = sum(k['profit'] for k in kt)
            return dict(n=len(kt), total_profit=round(tp * 10000) / 10000,
                        return_pct_max_holding=round(tp / peak * 100 * 10000) / 10000 if peak > 0 else 0,
                        max_concurrent_capital=peak), peak
        else:
            tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in recomputed]
            st = self.eng.compute_stats(tuples)
            return st, st['max_concurrent_capital']

    def compute_opg(self, filters, exclude_keys=None, periods=('y1', 'all'), fixed_amt=None):
        rec_by_mode = {m: self._mode_recomputed(m, filters, exclude_keys, fixed_amt) for m in MODES}
        cutoffs = self.eng.period_cutoffs
        result = {}
        for pk in periods:
            cutoff = cutoffs.get(pk, '0')
            result[pk] = {}
            for m in MODES:
                rp = [t for t in rec_by_mode[m] if cutoff == '0' or t['buy_date'] >= cutoff]
                st, peak = self.opg_mode_stats(m, rp)
                result[pk][m] = dict(st, _peak=peak)
        return result

    def attr_of(self, t, cache):
        bk = self.eng.base_key(t)
        if bk not in cache:
            fi = self.fi
            dk = self.eng._dim_key(t)
            mkt = self.eng._dims.get(dk, {}).get('mkt', '')
            cache[bk] = dict(sig=str(t[fi['signal']] or ''), rat=str(t[fi['rating']] or ''), mkt=mkt,
                             mm=str(t[fi['buy_date']] or '')[4:6],
                             dd=int(str(t[fi['buy_date']] or '')[6:8]) if len(str(t[fi['buy_date']] or '')) >= 8 else 0)
        return cache[bk]

    def excl_keys(self, pred):
        cache = {}
        ks = set()
        for mk in MODES:
            for t in self.eng._all_by_mode[mk]:
                if pred(self.attr_of(t, cache)): ks.add(self.eng.base_key(t))
        return ks

    def quad_keysets(self):
        QUAD_LABELS = ['rating_high', 'rating_mid', 'rating_low', 'etf_strong', 'etf_related', 'etf_approx',
                       'etf_has_track', 'sig_main', 'sig_aux', 'sig_special', 'sig_backup',
                       'mkt_a', 'mkt_hk', 'mkt_global', 'mkt_industry', 'mkt_concept']
        qks = {}
        for qk in QUAD_LABELS:
            ks = set()
            for mk, arr in self.eng._quad_trades[qk].items():
                for t in arr: ks.add(self.eng.base_key(t))
            qks[qk] = ks
        return qks


if __name__ == '__main__':
    oeng = OpgEngine(load_trades())
    eng = oeng.eng
    # 1) 基线
    base = oeng.compute_opg(AI_MACRO)
    print("=== v1.0.0 可操作口径基线(9模式) ===")
    for pk in ('all', 'y1'):
        print(f"[{pk}]")
        for m in MODES:
            s = base[pk][m]
            print(f"  {m}: 净利={s['total_profit']:+,.0f} 收益={s['return_pct_max_holding']:.2f}% 峰持仓={s['max_concurrent_capital']/10000:.1f}万 n={s['n']}")
    # 2) 剔除整象限(用户4象限)
    qks = oeng.quad_keysets()
    user4 = set()
    for k in ['etf_approx', 'etf_has_track', 'rating_high', 'mkt_hk']: user4 |= qks[k]
    st = oeng.compute_opg(AI_MACRO, exclude_keys=user4)
    print("\n=== 用户4象限剔除边际(v1.0.0 可操作口径) ===")
    for pk in ('all', 'y1'):
        row = [f"[{pk}] "]
        for m in MODES:
            d = st[pk][m]['total_profit'] - base[pk][m]['total_profit']
            row.append(f"{m}{d:+,.0f}")
        print(" ".join(row))
    # 3) 候选键 + 组合
    cands = [
        ('K2C5 港股追涨', lambda a: a['sig'] in ('buy_special', 'buy_backup') and a['mkt'] == 'hk'),
        ('K3 主关注×概念', lambda a: a['sig'] == 'buy' and a['mkt'] == 'concept'),
        ('K1 追×港股×1月下旬', lambda a: a['sig'] == 'buy_special' and a['mkt'] == 'hk' and a['mm'] == '01' and 21 <= a['dd'] <= 31),
        ('K6 高评级×(A∪概念)', lambda a: a['rat'] == 'high' and a['mkt'] in ('a', 'concept')),
        ('C1+C2+C5 最优组合', lambda a: (a['sig'] == 'buy' and a['mkt'] == 'concept') or (a['sig'] == 'buy_special' and a['mkt'] == 'hk') or (a['sig'] == 'buy_backup' and a['mkt'] == 'hk')),
    ]
    print("\n=== 候选键/组合剔除边际(v1.0.0 可操作口径) ===")
    for name, pred in cands:
        ks = oeng.excl_keys(pred)
        st = oeng.compute_opg(AI_MACRO, exclude_keys=ks)
        print(f"\n{name} 剔除n={len(ks)}")
        for pk in ('all', 'y1'):
            row = [f"  [{pk}] "]
            for m in ('A', 'G', 'F', 'H', 'I'):
                d = st[pk][m]['total_profit'] - base[pk][m]['total_profit']
                row.append(f"{m}{d:+,.0f}")
            print(" ".join(row))
