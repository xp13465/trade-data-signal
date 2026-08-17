# -*- coding: utf-8 -*-
"""凯利回测复现引擎(前端口径, lab.js 逐函数对齐)
目的: 精确复现前端 lab.js 在「默认 AI宏7键 + positionCap K1 每日资金池等分」口径下的象限统计
口径: 先 toggle 过滤 -> positionCap top-K(K=1) -> 每日资金池等分(每笔=10000/当日保留数) -> ETF主流费率重算 profit
输入: static-site/data/signal_kelly_trades.json (2026-08-15 02:38 批)
依赖: 无(纯标准库)
"""
import json, datetime, math
from collections import defaultdict

TRADES_PATH = '/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json'
FIELDS = ["signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code", "etf_name",
          "track_tier", "track_score", "match_method", "track_low_confidence", "buy_price", "sell_price",
          "shares", "profit", "return_pct", "hold_days", "sell_reason", "current_price", "market_state", "rating"]

# ===== 费率(前端默认 ETF主流) =====
FEE = dict(commission_rate=0.00005, min_commission=0.1, slippage=0.001,
           transfer_fee_rate_sh=0.00001, stamp_duty_rate=0)
BUY_AMOUNT = 10000
ORIG_SLIPPAGE = 0.001

# ===== 默认 AI宏7键 =====
AI_MACRO = dict(
    excludeSpecialBear=True, n2NovSpecialIndustry=True, janMidRating=True, janMidSpecial=True,
    r7MayReinforced=True, excludeAuxCross=True, greedy15=True,
    positionCap=True, positionCapK=1,
)

def load_trades(path=TRADES_PATH):
    with open(path) as f:
        data = json.load(f)
    return data

class KellyEngine:
    def __init__(self, trades_data):
        self.td = trades_data
        self.fIdx = {f: i for i, f in enumerate(FIELDS)}
        self.quads = trades_data['quadrants']
        self.buy_amount = trades_data.get('buy_amount', 10000)
        self.period_cutoffs = trades_data.get('period_cutoffs', {})
        self._dims = self._build_trade_dims()
        # 预存各象限各模式 trades(数组引用)
        self._quad_trades = {}
        for qk, v in self.quads.items():
            self._quad_trades[qk] = {mk: arr for mk, arr in v.items() if isinstance(arr, list)}
        # rating 三分区并集 = 全信号 all(按 mode)
        self._all_by_mode = {}
        for mk in self._quad_trades['rating_high']:
            arr = self._quad_trades['rating_high'].get(mk, []) + self._quad_trades['rating_mid'].get(mk, []) + self._quad_trades['rating_low'].get(mk, [])
            self._all_by_mode[mk] = arr

    def _build_trade_dims(self):
        dims = {}
        for qk, v in self.quads.items():
            parts = qk.split('_')
            dimType = parts[0]
            dimVal = '_'.join(parts[1:])
            for mk, arr in v.items():
                if not isinstance(arr, list): continue
                for t in arr:
                    key = self._dim_key(t)
                    if key not in dims: dims[key] = {}
                    dims[key][dimType] = dimVal
        return dims

    def _dim_key(self, t):
        fi = self.fIdx
        return '|'.join([str(t[fi['signal_date']]), str(t[fi['index_id']]), str(t[fi['signal']]),
                         str(t[fi['buy_date']]), str(t[fi['etf_code']]), str(t[fi['sell_date']])])

    def base_key(self, t):
        fi = self.fIdx
        return '|'.join([str(t[fi['signal_date']]), str(t[fi['index_id']]), str(t[fi['signal']]),
                         str(t[fi['buy_date']]), str(t[fi['etf_code']])])

    # ---- 特征 ----
    def _wd(self, bd):
        if not bd or len(bd) < 8: return -1
        y, m, d = int(bd[0:4]), int(bd[4:6]), int(bd[6:8])
        return datetime.date(y, m, d).weekday()  # 0=Mon..2=Wed, 与JS转换后一致

    def _bpb(self, price):
        if price is None: return ""
        if price <= 0.841441: return "vlow"
        if price <= 1.015314: return "low"
        if price <= 1.194593: return "mid"
        if price <= 1.446645: return "high"
        return "vhigh"

    def _feats(self, t):
        fi = self.fIdx
        bd = str(t[fi['buy_date']] or "")
        mm = bd[4:6] if len(bd) >= 6 else ""
        dd = int(bd[6:8]) if len(bd) >= 8 else 0
        sig = str(t[fi['signal']] or "")
        wd = self._wd(bd)
        bpb = self._bpb(t[fi['buy_price']])
        dk = self._dim_key(t)
        dm = self._dims.get(dk, {})
        mktD = dm.get('mkt', '')
        ratD = dm.get('rating', '')
        ts = float(t[fi['track_score']]) if t[fi['track_score']] is not None else 999
        etfD = str(t[fi['track_tier']] or "")
        q = math.ceil(int(mm) / 3) if mm else 0
        return dict(mm=mm, dd=dd, sig=sig, wd=wd, bpb=bpb, mktD=mktD, ratD=ratD, ts=ts, etfD=etfD, q=q)

    # ---- AI宏过滤谓词(与 _kellyPassesFadeFilters 一致) ----
    def passes_fade(self, t, filters=None):
        filters = filters or AI_MACRO
        fi = self.fIdx
        sig = str(t[fi['signal']] or "")
        bd = str(t[fi['buy_date']] or "")
        mm = bd[4:6] if len(bd) >= 6 else ""
        # 基础键
        if filters.get('excludeAux') and sig == "buy_aux": return False
        if filters.get('marketTiming') and t[fi['market_state']] is not True: return False
        if filters.get('excludeMonth') and mm in ("03", "05"): return False
        if filters.get('excludeRatingLow') and t[fi['rating']] == "low": return False
        if filters.get('excludeAuxCross') and sig == "buy_aux" and mm in ("03", "05"): return False
        if filters.get('excludeSpecialBear') and sig == "buy_special" and t[fi['market_state']] is False: return False
        # v3/v4/r3/jan 需要特征
        v3on = filters.get('n1MarTueHigh') or filters.get('n2NovSpecialIndustry') or filters.get('r8PureNonMay') or filters.get('n3NovSpecialMon') or filters.get('n4AMay') or filters.get('r7MayReinforced') or filters.get('n5MayVlow') or filters.get('n6MidMay') or filters.get('r10May6NonMay')
        v4on = filters.get('greedy7') or filters.get('greedy10') or filters.get('greedy15') or filters.get('v4cSimple') or filters.get('v4b') or filters.get('v4d') or filters.get('v4j') or filters.get('v4i') or filters.get('v4f') or filters.get('v4g') or filters.get('v4m') or filters.get('v4k')
        r3on = filters.get('a5NovMidSpecial') or filters.get('a45NovMidLateSpecial')
        janon = filters.get('janMidRating') or filters.get('janMidSpecial')
        if not (v3on or v4on or r3on or janon):
            return True
        f = self._feats(t)
        mm3, dd3, sig3, wd3, bpb3 = f['mm'], f['dd'], f['sig'], f['wd'], f['bpb']
        mktD3, ratD3, ts3, etfD3, q3 = f['mktD'], f['ratD'], f['ts'], f['etfD'], f['q']
        if v3on:
            if filters.get('n1MarTueHigh') and mm3 == "03" and wd3 == 2 and bpb3 == "high": return False
            if filters.get('n2NovSpecialIndustry') and sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry": return False
            if filters.get('r8PureNonMay') and ((mm3 == "03" and wd3 == 2 and bpb3 == "high") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or (sig3 == "buy_special" and mm3 == "11" and wd3 == 0)): return False
            if filters.get('n3NovSpecialMon') and sig3 == "buy_special" and mm3 == "11" and wd3 == 0: return False
            if filters.get('n4AMay') and mktD3 == "a" and mm3 == "05": return False
            if filters.get('r7MayReinforced') and ((mktD3 == "a" and mm3 == "05") or (ratD3 == "mid" and mm3 == "05") or (mm3 == "05" and bpb3 == "vlow") or (mm3 == "03" and wd3 == 2 and bpb3 == "high") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or (sig3 == "buy_special" and mm3 == "11" and wd3 == 0)): return False
            if filters.get('n5MayVlow') and mm3 == "05" and bpb3 == "vlow": return False
            if filters.get('n6MidMay') and ratD3 == "mid" and mm3 == "05": return False
            if filters.get('r10May6NonMay') and (mm3 == "05" or (mm3 == "03" and wd3 == 2 and bpb3 == "high") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or (sig3 == "buy_special" and mm3 == "11" and wd3 == 0) or (sig3 == "buy_special" and mm3 == "11" and bpb3 == "low") or (sig3 == "buy_special" and mm3 == "03" and mktD3 == "industry") or (mm3 == "03" and wd3 == 2 and sig3 == "buy_aux")): return False
        if v4on:
            if filters.get('v4cSimple') and mm3 == "03" and wd3 == 2 and sig3 == "buy_aux": return False
            if filters.get('v4b') and mktD3 == "a" and mm3 == "05" and sig3 == "buy_special" and etfD3 == "related": return False
            if filters.get('greedy7') and (
                (sig3 == "buy_special" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "03") or (sig3 == "buy_aux" and mm3 == "01") or
                (q3 == 2 and bpb3 == "vlow" and sig3 == "buy_aux" and mktD3 == "concept") or
                (sig3 == "buy" and mm3 == "01") or (mm3 == "03" and wd3 == 2 and mktD3 == "concept" and ratD3 == "low")): return False
            if filters.get('v4d') and mm3 == "12" and wd3 == 1 and sig3 == "buy_aux" and ts3 < 50: return False
            if filters.get('v4j') and mm3 == "05" and bpb3 == "vlow" and sig3 == "buy_special": return False
            if filters.get('v4i') and sig3 == "buy_special" and mm3 == "05" and mktD3 == "concept" and wd3 == 0: return False
            if filters.get('greedy10') and (
                (sig3 == "buy_special" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "03") or (sig3 == "buy_aux" and mm3 == "01") or
                (q3 == 2 and bpb3 == "vlow" and sig3 == "buy_aux" and mktD3 == "concept") or
                (sig3 == "buy" and mm3 == "01") or (mm3 == "03" and wd3 == 2 and mktD3 == "concept" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "12" and ts3 < 50) or (mm3 == "06" and bpb3 == "vlow" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "05")): return False
            if filters.get('v4f') and sig3 == "buy" and mm3 == "06" and wd3 == 2 and etfD3 == "related": return False
            if filters.get('v4g') and mktD3 == "global" and q3 == 1 and sig3 == "buy_aux" and ratD3 == "low": return False
            if filters.get('v4m') and sig3 == "buy_special" and mm3 == "09" and wd3 == 2: return False
            if filters.get('v4k') and sig3 == "buy" and mm3 == "01" and bpb3 == "high": return False
            if filters.get('greedy15') and (
                (sig3 == "buy_special" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "03") or (sig3 == "buy_aux" and mm3 == "01") or
                (q3 == 2 and bpb3 == "vlow" and sig3 == "buy_aux" and mktD3 == "concept") or
                (sig3 == "buy" and mm3 == "01") or (mm3 == "03" and wd3 == 2 and mktD3 == "concept" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "12" and ts3 < 50) or (mm3 == "06" and bpb3 == "vlow" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or
                (mm3 == "04" and wd3 == 1 and mktD3 == "concept" and ts3 < 50) or
                (mktD3 == "global" and q3 == 1 and sig3 == "buy_aux" and ratD3 == "low") or
                (mm3 == "01" and bpb3 == "low" and sig3 == "buy_special" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "09" and wd3 == 2)): return False
        if r3on:
            if filters.get('a5NovMidSpecial') and sig3 == "buy_special" and mm3 == "11" and 11 <= dd3 <= 20: return False
            if filters.get('a45NovMidLateSpecial') and sig3 == "buy_special" and mm3 == "11" and dd3 >= 11: return False
        if janon:
            if filters.get('janMidRating') and mm3 == "01" and 11 <= dd3 <= 20 and ratD3 == "mid": return False
            if filters.get('janMidSpecial') and sig3 == "buy_special" and mm3 == "01" and 11 <= dd3 <= 20: return False
        return True

    # ---- positionCap ----
    def _kept_keys(self, pool, K):
        kept = {}
        if not K or K <= 0 or not pool: return kept
        RATING_RANK = {'high': 0, 'mid': 1, 'low': 2, '': 3}
        SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3, '': 9}
        byDate = defaultdict(list)
        fi = self.fIdx
        for t in pool:
            sd = str(t[fi['signal_date']] or "")
            if not sd: continue
            byDate[sd].append(t)
        for sd, rows in byDate.items():
            def _rk(t):
                r = str(t[fi['rating']] or "")
                return RATING_RANK.get(r, 3)
            def _sg(t):
                s = str(t[fi['signal']] or "")
                return SIG_RANK.get(s, 9)
            rows.sort(key=lambda t: (-(float(t[fi['track_score']]) if t[fi['track_score']] is not None else -1),
                                     _rk(t), _sg(t), str(t[fi['buy_date']] or "")))
            for j in range(min(K, len(rows))):
                kept[self.base_key(rows[j])] = True
        return kept

    def _day_counts(self, kept):
        m = {}
        for k in kept:
            sd = str(k or "").split('|')[0]
            if sd: m[sd] = m.get(sd, 0) + 1
        return m

    def collect_base_pool(self, filters, exclude_keys=None):
        """收集基笔池(全信号过 toggle 过滤 + 去重), 可选排除 exclude_keys(baseKey set)"""
        pool, seen = [], set()
        fi = self.fIdx
        for rk in ('rating_high', 'rating_mid', 'rating_low'):
            for mk, arr in self._quad_trades[rk].items():
                for t in arr:
                    if not self.passes_fade(t, filters): continue
                    bk = self.base_key(t)
                    if bk in seen: continue
                    if exclude_keys and bk in exclude_keys: continue
                    seen.add(bk)
                    pool.append(t)
        return pool

    # ---- 每笔重算(与 _kellyRecomputeTrade 一致) ----
    def recompute(self, t, amt):
        fi = self.fIdx
        bp = t[fi['buy_price']] or 0
        sp = t[fi['sell_price']] or 0
        cp = t[fi['current_price']] or 0
        ec = t[fi['etf_code']] or ""
        sellDate = t[fi['sell_date']] or ""
        if bp <= 0: return 0.0, 0.0, 0.0
        closeBuy = bp / (1 + ORIG_SLIPPAGE)
        closeSell = (sp / (1 - ORIG_SLIPPAGE)) if sellDate else cp
        c = FEE['commission_rate']; s = FEE['slippage']; minC = FEE['min_commission']
        sh = FEE['transfer_fee_rate_sh'] if (ec.startswith('51') or ec.startswith('58')) else 0
        stamp = FEE['stamp_duty_rate']
        buyPriceNew = closeBuy * (1 + s)
        if buyPriceNew <= 0: return 0.0, 0.0, 0.0
        sharesNew = amt / (buyPriceNew * (1 + c + sh))
        grossNew = sharesNew * buyPriceNew
        commBuy = grossNew * c
        if commBuy < minC:
            sharesNew = (amt - minC) / (buyPriceNew * (1 + sh))
            grossNew = sharesNew * buyPriceNew
            commBuy = minC
        sellPriceNew = closeSell * (1 - s)
        sellAmountNew = sharesNew * sellPriceNew
        commSell = max(sellAmountNew * c, minC)
        transferFeeSell = sellAmountNew * sh
        stampDuty = sellAmountNew * stamp
        netNew = sellAmountNew - commSell - transferFeeSell - stampDuty
        profitNew = netNew - amt
        returnPctNew = profitNew / amt * 100
        shares0 = amt / closeBuy
        profit0 = shares0 * closeSell - amt
        feeCost = profit0 - profitNew
        return profitNew, returnPctNew, feeCost

    # ---- 统计(与 _kellyComputeStats 核心指标一致) ----
    def compute_stats(self, trades, period_key='all'):
        """trades: list of (profit, return_pct, fee_cost, buy_date, sell_date, hold_days, amount)"""
        n = len(trades)
        if n == 0:
            return dict(n=0, total_profit=0, win_rate=0, mean_return=0, return_pct_max_holding=0,
                        max_concurrent=0, max_concurrent_capital=0, total_fee_cost=0, total_invest=0)
        total_profit = sum(x[0] for x in trades)
        total_fee_cost = sum(x[2] for x in trades)
        wins = sum(1 for x in trades if x[0] > 0)
        total_amount = sum(x[6] for x in trades)
        mean_return = sum(x[1] for x in trades) / n
        # max concurrent capital(按日期分桶, 先减后加)
        SENT = "99999999"
        deltas, dates = {}, []
        for profit, rp, fee, bd, sd, hd, amt in trades:
            db = deltas.get(bd)
            if db is None: db = deltas[bd] = {'b': 0, 's': 0}; dates.append(bd)
            db['b'] += amt
            sd2 = sd or SENT
            ds = deltas.get(sd2)
            if ds is None: ds = deltas[sd2] = {'b': 0, 's': 0}; dates.append(sd2)
            ds['s'] += amt
        dates.sort()
        cur, maxC = 0, 0
        for d in dates:
            dd = deltas[d]
            cur -= dd['s']; cur += dd['b']
            if cur > maxC: maxC = cur
        maxConcCapital = round(maxC * 10000) / 10000
        rmph = (total_profit / maxConcCapital * 100) if maxConcCapital > 0 else 0
        # max concurrent(笔数)
        deltas2, dates2 = {}, []
        for profit, rp, fee, bd, sd, hd, amt in trades:
            db = deltas2.get(bd)
            if db is None: db = deltas2[bd] = {'b': 0, 's': 0}; dates2.append(bd)
            db['b'] += 1
            sd2 = sd or SENT
            ds = deltas2.get(sd2)
            if ds is None: ds = deltas2[sd2] = {'b': 0, 's': 0}; dates2.append(sd2)
            ds['s'] += 1
        dates2.sort()
        cur2, maxN = 0, 0
        for d in dates2:
            dd = deltas2[d]
            cur2 -= dd['s']; cur2 += dd['b']
            if cur2 > maxN: maxN = cur2
        return dict(n=n, total_profit=round(total_profit*10000)/10000, win_rate=round(wins/n*10000)/10000,
                    mean_return=round(mean_return*10000)/10000,
                    return_pct_max_holding=round(rmph*10000)/10000,
                    max_concurrent=maxN, max_concurrent_capital=maxConcCapital,
                    total_fee_cost=round(total_fee_cost*10000)/10000,
                    total_invest=round(total_amount*10000)/10000)

    # ---- 核心: 给定象限交易集合, 应用 AI宏过滤 + positionCap, 按周期输出 stats ----
    def compute_quad_stats(self, quad_trades_by_mode, filters=None, exclude_keys=None, periods=('y1','y3','y5','y10','all')):
        """quad_trades_by_mode: {modeKey: [trades]}; 返回 {period: {mode: stats}}
        positionCap 基笔池 = 全信号(全局), kept 集合全局共享"""
        filters = filters or AI_MACRO
        fi = self.fIdx
        # 全局 positionCap
        pool = self.collect_base_pool(filters, exclude_keys)
        kept = self._kept_keys(pool, filters.get('positionCapK', 1)) if filters.get('positionCap') else None
        day_counts = self._day_counts(kept) if kept else {}
        # 预过滤每个 mode 的交易
        toggled_by_mode = {}
        for mk, arr in quad_trades_by_mode.items():
            kept_t = []
            for t in arr:
                if not self.passes_fade(t, filters): continue
                if exclude_keys and self.base_key(t) in exclude_keys: continue
                if kept is not None and self.base_key(t) not in kept: continue
                kept_t.append(t)
            toggled_by_mode[mk] = kept_t
        result = {}
        cutoffs = self.period_cutoffs
        for pk in periods:
            cutoff = cutoffs.get(pk, "0")
            result[pk] = {}
            for mk, arr in toggled_by_mode.items():
                if cutoff and cutoff != "0":
                    trades = [t for t in arr if (str(t[fi['buy_date']] or "") >= cutoff)]
                else:
                    trades = arr
                recomputed = []
                for t in trades:
                    amt = BUY_AMOUNT / day_counts.get(str(t[fi['signal_date']]), 1) if day_counts else BUY_AMOUNT
                    p, rp, fee = self.recompute(t, amt)
                    recomputed.append((p, rp, fee, str(t[fi['buy_date']] or ""), str(t[fi['sell_date']] or ""), t[fi['hold_days']] or 0, amt))
                result[pk][mk] = self.compute_stats(recomputed, pk)
        return result

    def compute_quad_stats_fixed(self, quad_trades_by_mode, filters=None, exclude_keys=None, periods=('y1','y3','y5','y10','all')):
        """fixed 口径(每笔固定1万, 无 positionCap 金额联动, 但 kept 仍过滤)对照"""
        filters = filters or AI_MACRO
        fi = self.fIdx
        pool = self.collect_base_pool(filters, exclude_keys)
        kept = self._kept_keys(pool, filters.get('positionCapK', 1)) if filters.get('positionCap') else None
        result = {}
        cutoffs = self.period_cutoffs
        for pk in periods:
            cutoff = cutoffs.get(pk, "0")
            result[pk] = {}
            for mk, arr in quad_trades_by_mode.items():
                trades = []
                for t in arr:
                    if not self.passes_fade(t, filters): continue
                    if exclude_keys and self.base_key(t) in exclude_keys: continue
                    if kept is not None and self.base_key(t) not in kept: continue
                    if cutoff and cutoff != "0" and str(t[fi['buy_date']] or "") < cutoff: continue
                    p, rp, fee = self.recompute(t, BUY_AMOUNT)
                    trades.append((p, rp, fee, str(t[fi['buy_date']] or ""), str(t[fi['sell_date']] or ""), t[fi['hold_days']] or 0, BUY_AMOUNT))
                result[pk][mk] = self.compute_stats(trades, pk)
        return result


if __name__ == '__main__':
    td = load_trades()
    eng = KellyEngine(td)
    # 对账: 全信号 all A/G 模式 K1 每日池口径
    for mode in ('A', 'G'):
        stats = eng.compute_quad_stats(eng._all_by_mode, periods=('all','y1'))['all'][mode]
        print(f"all mode={mode} 每日池: 净利={stats['total_profit']:+,} n={stats['n']} 胜率={stats['win_rate']*100:.1f}% 峰资收益率={stats['return_pct_max_holding']:.2f}% 峰持仓={stats['max_concurrent_capital']/10000:.1f}万")
        st2 = eng.compute_quad_stats_fixed(eng._all_by_mode, periods=('all',))['all'][mode]
        print(f"all mode={mode} fixed:   净利={st2['total_profit']:+,} n={st2['n']} 峰资收益率={st2['return_pct_max_holding']:.2f}% 峰持仓={st2['max_concurrent_capital']/10000:.1f}万")
