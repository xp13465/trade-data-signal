# -*- coding: utf-8 -*-
"""Task#11 亏单延长持有双卖法 可行性穷举回测(cc 侧, Claude Code 执行方)。

【目的】基线「持有10个交易日卖出」(引擎模式A固定10天池口径)到期必有亏损单;
    V1 = 亏损单不卖, 等回本(费后净回本 net≥本金1万)当日收盘再卖;
    V2 = 亏损单不卖, 等该指数真实卖出信号出现就卖——亏也卖=承认止损。
    三降亏模式 S06(大盘领先动态 a9/new15) / A(on9 进攻王) / NEW14(+1·15键=new15) × 卖法全矩阵。

【方法口径】
  - 选笔层复用项目权威机具(mine24/mine27/sim_core):
      pool=signal_kelly_trades.json mode A 跨16象限去重基笔池; 费后每笔K1账本=sim_core.calc_row
      (FP_DEF etf_def 档 佣万3/min5+滑千1+沪过户万0.1+卖出印花万5), PRIN=10000;
      组合层=每日K1补位 + cap13 并发上限重放(mine27.replay3 'v2回补极简' + stats_ext)。
  - 模式选笔(§23.13 三源核实): p0/p1/a9(叠加)=prepare_rows 复刻 mine24_compare L109-154;
      new14=重构黑名单(mine24 L156-197 复刻); new15=new14∪X1(loss_rules RULE_SPECS['X1'] 同源);
      s06=逐信号日读 kelly_mode_s06_state.json effective_mode(T收盘判定T+1生效;coverage前fallback off_base计数)。
  - 延长持有(V1/V2): 仅改「基线10日到期 pnl<0」的亏损单出场:
      V1 首个净回本日收盘卖(sell_with_fees(shares*,nav[d]).net>=PRIN);
      V2 该指数基线卖日后首个 sell 类信号日卖(引擎 G/H/I 同款当日收盘成交 signal_kelly_backtest.py L654-708 同法):
        主口径 ('sell','sell_stop_loss')=引擎H档; 敏感性 sell-only(G档语义)/T+1开盘成交(gap式同 v1.1.4 买入口径);
      数据尾未回本/未遇信号=censored 尾日估值(calc_row holding 分支镜像)。⚠"D档"无对应定义待用户拍板。
  - 防前视(§5.1⑥): t 日决策只用 ≤t 数据, 无全期统计量参与逐笔判定。
【输入依赖】static-site/data/signal_kelly_trades.json + static-site/data/kelly_mode_s06_state.json +
    docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/mine10_features.json +
    data/sentiment.db(signal_daily 只读) + trade-data/data/etf_national_team.db(etf_daily 只读)
【输出】本目录 cc_anchors.json / cc_selection.json / cc_variants.json / cc_matrix.json
【复现命令】python3 docs/kelly/backtest-ai/hold-ext-pk-20260827/cc/cc_hold_ext_backtest.py --anchors   # 先验锚点
            python3 docs/kelly/backtest-ai/hold-ext-pk-20260827/cc/cc_hold_ext_backtest.py --all      # 锚点+全矩阵
【数据截止】trades generated_at 运行时打印; 关键口径一句话: modeA去重池×三模式选笔(K1补位)→
    基线10td固定卖 vs 亏单延长{V1回本,V2等卖出信号} 费后 FP_DEF K1 账本 + cap13 重放全维度对比。
"""
import os, sys, json, bisect, sqlite3, datetime, argparse, statistics

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../../../'))
M21 = os.path.join(REPO, 'docs/kelly/analysis/scripts/sim_window_loss_mining_20260822')
sys.path.insert(0, M21)
sys.path.insert(0, REPO)

from sim_core import load, build_mode_pool, passes_fade, DEFAULT_FILTERS, active_month_mask, PRIN, base_key, calc_row, buy_with_fees, sell_with_fees, FP_DEF  # noqa
import r2_common as R  # noqa
import mine27_g_exhaustive_simplified as M27  # finish_pool/replay3/stats_ext/BEARS26

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_JSON = os.path.join(REPO, 'static-site/data/signal_kelly_trades.json')
S06_JSON = os.path.join(REPO, 'static-site/data/kelly_mode_s06_state.json')
FEATS_PATH = os.path.join(M21, 'data/mine10_features.json')
ETF_DB_CANDIDATES = [os.path.join(os.path.dirname(REPO), 'trade-data/data/etf_national_team.db'),
                     os.path.join(REPO, 'data/etf_national_team.db')]
SENT_DB = os.path.join(REPO, 'data/sentiment.db')

ANCHOR = dict(P0=66530.38, P1=73102.53, NEW14=122648.33, NEW14_MDD=-4178.01)
A9_MARG_PUBLISHED = 46007.00
A_SUB = ('T1', 'Q1', 'M1', 'V1', 'R1', 'R2a', 'R2b', 'R2g')
VARIANTS = ['BASE', 'V1', 'V2', 'V2G', 'V2T1']
CAP_MAIN = 13


def ro(path):
    assert os.path.exists(path), path
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def c1_hit(t, fi):
    return t[fi['signal']] in ('buy_aux', 'buy_backup') and (t[fi['market_tier']] or '') == '牛市·主升'


def x1_hit(t, fi):
    v = t[fi['track_tier']]
    return v is None or str(v) == 'none'


class Engine:
    def __init__(self):
        self.tr, self.fi = load(TRADES_JSON)
        self.gen_at = self.tr.get('generated_at')
        self.pool = build_mode_pool(self.tr, self.fi, 'A')
        self.fi_ = self.fi
        self.mD, self.eD, self.rD = len(self.fi), len(self.fi) + 1, len(self.fi) + 2
        self.rows8, _ = R.prepare_rows()
        M27.finish_pool(self.pool, self.fi)
        R.init(self.rows8, self.fi)
        feats = json.load(open(FEATS_PATH))
        from mine21_bigtour import build_rules
        from mine22_joint import build_r2
        self.rules = build_rules(feats, self.fi)
        self.rules.update(build_r2(self.fi))
        with open(os.path.join(M21, 'data/mine24_compare.json')) as f:
            m24 = json.load(f)
        self.new14_keys = list(m24['new_keys'])
        self._memo = {}
        self._rows8_set = {base_key(t, self.fi) for t in self.rows8}
        self._hc1 = {base_key(t, self.fi) for t in self.rows8 if c1_hit(t, self.fi)}
        self.g_all = self._group_sorted(self.pool)
        self.g_8 = self._group_sorted(self.rows8)
        with open(S06_JSON) as f:
            s06 = json.load(f)
        self.s06_on = s06.get('on_base') or 'a9'
        self.s06_off = s06.get('off_base') or 'new15'
        self.s06_cov_start = s06.get('coverage_start')
        self.s06_daily = {e['date']: e['effective_mode'] for e in s06['daily']}
        self.s06_pre_n = 0

    def _group_sorted(self, rows):
        g = {}
        for t in rows:
            g.setdefault(str(t[0]), []).append(t)
        for sd in g:
            g[sd].sort(key=lambda t: t[R.IDX_SKEY])
        return g

    def rule_hits(self, c, on_rows8=False):
        key = ('rule', c, on_rows8)
        hs = self._memo.get(key)
        if hs is None:
            src = self.rows8 if on_rows8 else self.pool
            hs = {base_key(t, self.fi) for t in src if self.rules[c](t)}
            self._memo[key] = hs
        return hs

    def hist_hits_singlekey(self, k):
        key = ('hist', k)
        hs = self._memo.get(key)
        if hs is None:
            f = {kk: False for kk in DEFAULT_FILTERS}
            f[k] = True
            mm = active_month_mask(f)
            hs = {base_key(t, self.fi) for t in self.pool
                  if not passes_fade(t, self.fi, f, mm, self.mD, self.eD, self.rD)}
            self._memo[key] = hs
        return hs

    @property
    def new14_blk(self):
        key = ('blk', 'new14')
        blk = self._memo.get(key)
        if blk is None:
            blk = set()
            df_keys = set(DEFAULT_FILTERS)
            for k in self.new14_keys:
                blk |= self.hist_hits_singlekey(k) if k in df_keys else self.rule_hits(k)
            self._memo[key] = blk
        return blk

    @property
    def x1_blk(self):
        return {base_key(t, self.fi) for t in self.pool if x1_hit(t, self.fi)}

    @property
    def a9_extra_blk(self):
        key = ('blk', 'a9extra')
        blk = self._memo.get(key)
        if blk is None:
            blk = set(self._hc1)
            for c in A_SUB:
                blk |= self.rule_hits(c, on_rows8=True)
            self._memo[key] = blk
        return blk

    def select(self, mode):
        """返回入选笔列表(K1 每信号日按 skey 取首个未拦者)。"""
        fi = self.fi
        out = []
        if mode in ('p0', 'p1', 'a9'):
            extra = set() if mode == 'p0' else (self._hc1 if mode == 'p1' else self.a9_extra_blk)
            for sd in sorted(self.g_8):
                for t in self.g_8[sd]:
                    if base_key(t, fi) not in extra:
                        out.append(t)
                        break
            return out
        if mode in ('new14', 'new15'):
            blk = self.new14_blk | (self.x1_blk if mode == 'new15' else set())
            for sd in sorted(self.g_all):
                for t in self.g_all[sd]:
                    if base_key(t, fi) not in blk:
                        out.append(t)
                        break
            return out
        if mode == 's06':
            a9_blk = self.a9_extra_blk
            n15_blk = self.new14_blk | self.x1_blk
            sds_a9 = sds_n15 = 0
            for sd in sorted(self.g_all):
                b = self.s06_daily.get(sd)
                if b is None:
                    b = self.s06_off
                    self.s06_pre_n += 1
                if b == self.s06_on:
                    grp = self.g_8.get(sd, [])
                    sds_a9 += 1
                    for t in grp:
                        bk = base_key(t, fi)
                        if bk not in a9_blk:
                            out.append(t)
                            break
                else:
                    sds_n15 += 1
                    for t in self.g_all[sd]:
                        if base_key(t, fi) not in n15_blk:
                            out.append(t)
                            break
            self.s06_day_stats = dict(days_on=self.s06_on, n_a9_days=sds_a9, n_new15_days=sds_n15,
                                      pre_coverage_dates_filled_offbase=self.s06_pre_n)
            return out
        raise ValueError(mode)


def ledger_stats(sel, fi):
    st = R.stats_of(sel)
    idx_pnl = R.IDX_PNL
    realized = [t for t in sel if str(t[fi['sell_date']] or '')]
    cens = [t for t in sel if not str(t[fi['sell_date']] or '')]
    bys = {}
    for t in realized:
        d = str(t[fi['sell_date']])
        bys[d] = bys.get(d, 0.0) + t[idx_pnl]['pnlYuan']
    mdd, trough = dd_of(bys)
    win_r = sum(1 for t in realized if t[idx_pnl]['pnlYuan'] > 0)
    tot_r = sum(t[idx_pnl]['pnlYuan'] for t in realized)
    tot_c = sum(t[idx_pnl]['pnlYuan'] for t in cens)
    return dict(n=len(sel), total=round(st['total'], 2), total_realized=round(tot_r, 2),
                total_censored_open=round(tot_c, 2), n_realized=len(realized), n_censored=len(cens),
                win_rate_realized_pct=round(win_r / max(len(realized), 1) * 100, 1),
                win_rate_incl_cens_pct=st['winRate'], mdd_realized=mdd, mdd_trough=trough)


def dd_of(bys):
    cum = peak = 0.0
    mdd = 0.0
    trough = None
    for d in sorted(bys):
        cum += bys[d]
        if cum > peak:
            peak = cum
        if cum - peak < mdd:
            mdd = cum - peak
            trough = d
    return round(mdd, 2), trough


def load_prices(codes):
    nav, opn, cls = {}, {}, {}
    sdates = {}
    db = next((p for p in ETF_DB_CANDIDATES if os.path.exists(p)), None)
    assert db, 'etf DB 未找到'
    conn = ro(db)
    codes = list(codes)
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        ph = ','.join('?' * len(batch))
        for code, date, nv, o, c in conn.execute(
                f'SELECT etf_code,date,accum_nav,open,close FROM etf_daily '
                f'WHERE etf_code IN ({ph}) AND accum_nav IS NOT NULL ORDER BY etf_code,date', batch):
            nav.setdefault(code, {})[date] = nv
            if o is not None:
                opn.setdefault(code, {})[date] = o
            if c is not None:
                cls.setdefault(code, {})[date] = c
    conn.close()
    for c in nav:
        sdates[c] = sorted(nav[c].keys())
    return nav, opn, cls, sdates


def load_sell_timeline():
    conn = ro(SENT_DB)
    tl = {}
    for d, iid, sig in conn.execute(
            "SELECT date,index_id,signal FROM signal_daily WHERE signal IN ('sell','sell_stop_loss') "
            'ORDER BY index_id,date'):
        tl.setdefault(iid, []).append((d, sig))
    conn.close()
    return tl


class Extender:
    """延长持有变体引擎。"""

    def __init__(self, eng):
        self.eng = eng
        self.fi = eng.fi
        fi = self.fi
        codes = sorted({t[fi['etf_code']] for t in eng.pool})
        iids = sorted({t[fi['index_id']] for t in eng.pool})
        print(f'[Extender] loading prices for {len(codes)} etfs ...', flush=True)
        self.nav, self.opn, self.cls, self.sdates = load_prices(codes)
        self.today_str = max((ds[-1] for ds in self.sdates.values() if ds), default=None)
        print(f'[Extender] price series loaded, today_str={self.today_str}', flush=True)
        print(f'[Extender] loading sell timeline ({len(iids)} index_ids) ...', flush=True)
        full_tl = load_sell_timeline()
        self.tl = {iid: full_tl.get(iid, []) for iid in iids}
        self.first_free_date = min(str(t[0]) for t in eng.pool)

    def shares_of(self, t):
        bp = float(t[self.fi['buy_price']] or 0)
        code = t[self.fi['etf_code']] or ''
        return buy_with_fees(PRIN, bp, code, FP_DEF)['shares']

    def net_at(self, t, d):
        code = t[self.fi['etf_code']] or ''
        nv = self.nav.get(code, {}).get(d)
        if nv is None:
            return None
        sr = sell_with_fees(self.shares_of(t), nv, code, FP_DEF)
        return sr['net']

    def cens_price(self, t):
        code = t[self.fi['etf_code']] or ''
        ds = self.sdates.get(code) or []
        ref = self.today_str
        cand = [d for d in ds if ref is None or d <= ref]
        if not cand:
            return None, None
        d = cand[-1]
        return d, self.nav[code][d]

    def find_v1(self, t, after_d):
        code = t[self.fi['etf_code']] or ''
        ds = self.sdates.get(code) or []
        i = bisect.bisect_right(ds, after_d)
        for d in ds[i:]:
            nt = self.net_at(t, d)
            if nt is not None and nt >= PRIN:
                return d, True
        return None, False

    def find_v2(self, t, after_d, types, allow_no_next_skip=True, t1_exec=False):
        code = t[self.fi['etf_code']] or ''
        ds = self.sdates.get(code) or []
        iid = t[self.fi['index_id']]
        for d, sig in self.tl.get(iid, []):
            if d <= after_d or sig not in types:
                continue
            if self.nav.get(code, {}).get(d) is None:
                continue  # 引擎同款守卫: 该ETF当日无价格不可成交 → 看下一信号
            if not t1_exec:
                return d, self.nav[code][d], 'close'
            j = bisect.bisect_right(ds, d)
            if j < len(ds):
                dn = ds[j]
                cd, od = self.cls.get(code, {}).get(d), self.opn.get(code, {}).get(dn)
                if cd and od:
                    eff = self.nav[code][d] * (od / cd)
                    return dn, eff, 'next_open'
            if allow_no_next_skip:
                continue
        return None, None, None

    def make_row(self, t, sell_d=None, sell_nav=None, censor=False):
        t2 = list(t)
        fi = self.fi
        if censor:
            d, nv = self.cens_price(t)
            if nv is None:
                t2[R.IDX_PNL] = dict(t[R.IDX_PNL])
                return t2, None
            t2[fi['sell_date']] = ''
            t2[fi['current_price']] = round(nv, 6)
            c = calc_row(t2, fi)
        else:
            t2[fi['sell_date']] = sell_d
            t2[fi['sell_price']] = round(sell_nav, 6)
            t2[fi['current_price']] = 0
            code = t[fi['etf_code']] or ''
            sr = sell_with_fees(self.shares_of(t), sell_nav, code, FP_DEF)
            bp = float(t[fi['buy_price']] or 0)
            br = buy_with_fees(PRIN, bp, code, FP_DEF)
            pnl = sr['net'] - PRIN
            c = dict(isHolding=False, pnlYuan=pnl, pnlPct=pnl / PRIN * 100,
                     buyFee=br['commission'] + br['transferFee'],
                     sellFee=sr['commission'] + sr['transferFee'] + sr['stampDuty'])
        t2[R.IDX_PNL] = c
        return t2, c

    def baseline_info(self, t):
        fi = self.fi
        bd = str(t[fi['signal_date']] or '')
        sd = str(t[fi['sell_date']] or '')
        pnl = t[R.IDX_PNL]['pnlYuan']
        return bd, sd, pnl

    def build_variants(self, sel):
        """返回 variants dict + loser 明细。sel 的行即 BASE(共享对象只读)。"""
        fi = self.fi
        res = {'BASE': list(sel)}
        pos_of = {id(t): i for i, t in enumerate(sel)}
        tails = 0
        plans = []   # (t, base_pnl, base_sell)
        for t in sel:
            bd, sd, pnl = self.baseline_info(t)
            if not sd:
                tails += 1
                continue
            if pnl < 0:
                plans.append((t, pnl, sd))
        for name in ['V1', 'V2', 'V2G', 'V2T1']:
            res[name] = list(sel)
        detail = dict(v1=[], v2=[], v2g=[], v2t1=[])
        ext_days_map = {'V1': [], 'V2': [], 'V2G': [], 'V2T1': []}
        censor_cnt = {v: 0 for v in ext_days_map}
        deltas = {v: [] for v in ext_days_map}
        for t, p0, sd in plans:
            # V1
            d, ok = self.find_v1(t, sd)
            row, c = (self.make_row(t, sell_d=d, sell_nav=self.nav[t[fi['etf_code']]][d]) if ok
                      else self.make_row(t, censor=True))
            res['V1'][pos_of[id(t)]] = row
            censor_cnt['V1'] += 0 if ok else 1
            deltas['V1'].append((c['pnlYuan'] - p0) if c else 0.0)
            detail['v1'].append(dict(sd=str(t[0]), etf=t[fi['etf_code']], base_pnl=round(p0, 2),
                                     exit=None if not ok else d, pnl=round(c['pnlYuan'], 2) if c else None))
            if ok:
                code = t[fi['etf_code']]
                i0 = bisect.bisect_left(self.sdates[code], sd)
                i1 = bisect.bisect_left(self.sdates[code], d)
                ext_days_map['V1'].append(i1 - i0)
            # V2 family
            for nm, types, t1x in [('V2', ('sell', 'sell_stop_loss'), False),
                                   ('V2G', ('sell',), False),
                                   ('V2T1', ('sell', 'sell_stop_loss'), True)]:
                d2, nv2, how = self.find_v2(t, sd, types, t1_exec=t1x)
                row2, c2 = (self.make_row(t, sell_d=d2, sell_nav=nv2) if d2
                            else self.make_row(t, censor=True))
                res[nm][pos_of[id(t)]] = row2
                censor_cnt[nm] += 0 if d2 else 1
                deltas[nm].append((c2['pnlYuan'] - p0) if c2 else 0.0)
                bucket = {'V2': detail['v2'], 'V2G': detail['v2g'], 'V2T1': detail['v2t1']}[nm]
                bucket.append(dict(sd=str(t[0]), etf=t[fi['etf_code']], base_pnl=round(p0, 2),
                                   exit=d2, how=how, pnl=round(c2['pnlYuan'], 2) if c2 else None))
                if d2:
                    code = t[fi['etf_code']]
                    i0 = bisect.bisect_left(self.sdates[code], sd)
                    i1 = bisect.bisect_left(self.sdates[code], d2)
                    ext_days_map[nm].append(max(i1 - i0, 1))
        meta = dict(n_loser_plans=len(plans), n_tail_holding=tails, censor_counts=censor_cnt,
                    ext_days={k: dist_stats(v) for k, v in ext_days_map.items()},
                    delta={k: delta_stats(v) for k, v in deltas.items()})
        return res, meta, detail


def dist_stats(xs):
    if not xs:
        return dict(n=0)
    xs2 = sorted(xs)

    def pct(p):
        i = min(int(p * (len(xs2) - 1)), len(xs2) - 1)
        return xs2[i]
    buckets = {'1-5': 0, '6-10': 0, '11-20': 0, '21-40': 0, '41-80': 0, '>80': 0}
    for x in xs:
        k = '1-5' if x <= 5 else '6-10' if x <= 10 else '11-20' if x <= 20 else '21-40' if x <= 40 \
            else '41-80' if x <= 80 else '>80'
        buckets[k] += 1
    return dict(n=len(xs), mean=round(sum(xs) / len(xs), 1), p50=pct(0.5), p90=pct(0.9),
                max=xs2[-1], buckets=buckets)


def delta_stats(xs):
    if not xs:
        return dict(n=0)
    pos = [x for x in xs if x > 0]
    neg = [x for x in xs if x < 0]
    zer = len(xs) - len(pos) - len(neg)
    return dict(n=len(xs), improved_n=len(pos), worsened_n=len(neg), zero_n=zer,
                pos_part=round(sum(pos), 2), neg_part=round(sum(neg), 2),
                net_delta=round(sum(xs), 2))


def occupancy(rows_base, rows_var, today_str, sdates_of):
    """额外占用 sweep(diff 法): 区间=[buy_date, exit); censored 视为占用至 today_str。"""
    def intervals(rows):
        out = []
        for t in rows:
            b = str(t[buy_i] or '')
            e = str(t[sell_i] or '')
            if not b:
                continue
            e = e if e else today_str
            if e <= b:
                continue
            out.append((b, e))
        return out
    buy_i = FI_BUY
    sell_i = FI_SELL

    def series(ivs):
        delta = {}
        for b, e in ivs:
            delta[b] = delta.get(b, 0) + 1
            delta[e] = delta.get(e, 0) - 1
        pts = sorted(delta)
        cur = 0
        prev = None
        curve = []
        for p in pts:
            if prev is not None and cur > 0:
                curve.append((prev, p, cur))
            cur += delta[p]
            prev = p
        if cur > 0 and prev is not None:
            curve.append((prev, today_str, cur))
        return curve
    cb = series(intervals(rows_base))
    cv = series(intervals(rows_var))
    # 合并事件轴求逐段差
    starts = sorted({s for s, _, _ in cb} | {s for s, _, _ in cv})

    def level(curve, x):
        val = 0
        for s, e, c in curve:
            if s <= x < e:
                val = c
                break
        return val
    peak_open_v = 0
    peak_extra = 0
    area_extra_ydays = 0
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else today_str
        gap = max((datetime.date(int(e[:4]), int(e[4:6]), int(e[6:8])) -
                   datetime.date(int(s[:4]), int(s[4:6]), int(s[6:]))).days, 0)
        lv = level(cv, s)
        lb = level(cb, s)
        peak_open_v = max(peak_open_v, lv)
        d = lv - lb
        if d > 0:
            peak_extra = max(peak_extra, d)
            area_extra_ydays += d * gap
    return dict(peak_open_n=peak_open_v, peak_open_yuan=peak_open_v * PRIN,
                peak_extra_n=peak_extra, peak_extra_yuan=peak_extra * PRIN,
                extra_area_wan_yuan_days=round(area_extra_ydays * PRIN / 10000, 0))


# ══════════════════════════ 主流程 ══════════════════════════
FI_BUY = FI_SELL = None


def run_anchors(eng):
    sel = {m: eng.select(m) for m in ['p0', 'p1', 'a9', 'new14', 'new15', 's06']}
    res = {}
    for m, s in sel.items():
        st = R.stats_of(s)
        row = dict(n=st['n'], total=st['total'], holding=st['holding'])
        if m == 'new14':
            bys = {}
            for t in s:
                d = str(t[eng.fi['sell_date']] or '')
                if d:
                    bys[d] = bys.get(d, 0.0) + t[R.IDX_PNL]['pnlYuan']
            mdd, tr = dd_of(bys)
            row['mdd_realized'] = mdd
            row['mdd_trough'] = tr
        if m == 'a9':
            row['margin_vs_p1'] = round(st['total'] - R.stats_of(sel['p1'])['total'], 2)
            row['published_margin_drift_ref'] = A9_MARG_PUBLISHED
        if m == 's06':
            row.update(getattr(eng, 's06_day_stats', {}))
        res[m] = row
        print(f'[anchors] {m}: {row}')
    checks = dict(
        p0_total=float(res['p0']['total']), anchor_p0=ANCHOR['P0'],
        p1_total=float(res['p1']['total']), anchor_p1=ANCHOR['P1'],
        new14_total=float(res['new14']['total']), anchor_new14=ANCHOR['NEW14'],
        new14_mdd=float(res['new14'].get('mdd_realized', 0)), anchor_mdd=ANCHOR['NEW14_MDD'])
    print('[anchors] drift check:', json.dumps(checks, ensure_ascii=False))
    out = dict(generated_at=eng.gen_at, anchors_published=ANCHOR, observed=res,
               drift=checks,
               pool_track_tier_none=sum(1 for t in eng.pool if x1_hit(t, eng.fi)),
               note='发布锚点基于 2026-08-23~24 时点数据; 产物每日重生新增尾段交易日致小幅漂移属预期')
    with open(os.path.join(OUT_DIR, 'cc_anchors.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return sel


def replay_pack(rows_sel, fi, cap, span_years, near_cut):
    day_sel = {}
    for t in rows_sel:
        day_sel[str(t[0])] = t
    rp = M27.replay3(day_sel, fi, cap, 'v2回补极简') if cap else M27.replay3(day_sel, fi, None, 'v2回补极简')
    budget = cap * PRIN if cap else 0
    st = M27.stats_ext(rp, fi, cap, budget, span_years, near_cut)
    keep = ['n_bought', 'n_forced_liq', 'n_skipped', 'n_natural_sell', 'n_holding_end',
            'realized_pnl', 'unrealized_pnl', 'total_merged', 'realized_winrate',
            'peak_pos_n', 'peak_occupancy_yuan', 'ops_per_year', 'skipped_mtm_if_bought']
    out = {k: st.get(k) for k in keep}
    mm = st.get('mdd_merged_terminal') or {}
    out['mdd_merged'] = mm.get('mdd') if isinstance(mm, dict) else mm
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--anchors', action='store_true')
    ap.add_argument('--all', action='store_true')
    a = ap.parse_args()
    eng = Engine()
    print(f'data generated_at={eng.gen_at} poolA_n={len(eng.pool)} rows8_n={len(eng.rows8)} '
          f'range={min(str(t[0]) for t in eng.pool)}~{max(str(t[0]) for t in eng.pool)} '
          f'track_tier_none={sum(1 for t in eng.pool if x1_hit(t, eng.fi))}')
    sel = run_anchors(eng)
    if not a.all:
        return

    fi = eng.fi
    ext = Extender(eng)
    globals()['FI_BUY'] = fi['buy_date']
    globals()['FI_SELL'] = fi['sell_date']

    today_str = ext.today_str
    data_end = max(x for x in [today_str] + [str(t[0]) for t in eng.pool])
    first_sd = min(str(t[0]) for t in eng.pool)
    last_sd = max(str(t[0]) for t in eng.pool)
    span_years = round((datetime.date(int(last_sd[:4]), int(last_sd[4:6]), int(last_sd[6:])) -
                        datetime.date(int(first_sd[:4]), int(first_sd[4:6]), int(first_sd[6:]))).days / 365.25, 2)
    dc = datetime.date(int(data_end[:4]), int(data_end[4:6]), int(data_end[6:])) - datetime.timedelta(days=365)
    near_cut = dc.strftime('%Y%m%d')

    MODES_RUN = ['s06', 'a9', 'new15', 'new14', 'p0', 'p1']
    matrix = dict(
        meta=dict(executor='Claude Code(cc侧)', generated_at=eng.gen_at, today_str=today_str,
                  span_years=span_years, near1y_cutoff=near_cut, cap_main=CAP_MAIN,
                  fee='FP_DEF etf_def 佣万3/min5+滑千1+沪过户万0.1+卖印花万5, PRIN=10000(K1账本)',
                  replay_method="mine27.replay3 'v2回补极简' cap13",
                  variants_note='BASE=10td固定卖; V1=亏单等净回本收盘卖; V2=亏单等sell+sell_stop_loss信号日收盘卖;'
                                ' V2G=sell-only; V2T1=V2次日开盘成交(敏感性)',
                  v2_types_main=('sell', 'sell_stop_loss'), d_tier_pending='用户"D档"未检索到定义, 待拍板'),
        ledger={}, replay_cap13={}, cap_sens={}, occupancy={}, yearly={}, bears={},
        extension_meta={}, near1y={})

    selection_out = {}
    variants_detail = {}

    for m in MODES_RUN:
        base_rows = sel[m]
        var_rows, meta, detail = ext.build_variants(base_rows)
        matrix['ledger'][m] = {}
        matrix['replay_cap13'][m] = {}
        matrix['cap_sens'][m] = {}
        matrix['occupancy'][m] = {}
        matrix['yearly'][m] = {}
        matrix['bears'][m] = {}
        matrix['near1y'][m] = {}
        for vn in VARIANTS:
            rows = var_rows[vn]
            matrix['ledger'][m][vn] = ledger_stats(rows, fi)
            matrix['replay_cap13'][m][vn] = replay_pack(rows, fi, CAP_MAIN, span_years, near_cut)
            cs = {'cap13': matrix['replay_cap13'][m][vn]['total_merged']}
            for capx in (20, None):
                pk = replay_pack(rows, fi, capx, span_years, near_cut)
                cs['nocap' if capx is None else f'cap{capx}'] = pk['total_merged']
                if vn == 'V2' and capx == 20:
                    pass
            matrix['cap_sens'][m][vn] = cs
            try:
                matrix['occupancy'][m][vn] = occupancy(var_rows['BASE'], rows, today_str, ext.sdates)
            except Exception as ex:
                matrix['occupancy'][m][vn] = dict(error=str(ex))
            yy = {}
            for t in rows:
                y = str(t[0])[:4]
                yy.setdefault(y, 0.0)
                yy[y] += t[R.IDX_PNL]['pnlYuan']
            matrix['yearly'][m][vn] = {y: round(v, 2) for y, v in sorted(yy.items())}
            br = {}
            for lab, w1, w2 in M27.BEARS26:
                ws = [t for t in rows if w1 <= str(t[0]) <= (w2 or '99999999')]
                br[lab] = dict(n=len(ws), total=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in ws), 2))
            matrix['bears'][m][vn] = br
            nw = [t for t in rows if str(t[0]) >= near_cut]
            matrix['near1y'][m][vn] = dict(n=len(nw), total=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in nw), 2))
        matrix['extension_meta'][m] = meta
        selection_out[m] = dict(n=len(base_rows),
                                first5=[dict(sd=str(t[0]), etf=t[fi['etf_code']], sig=t[fi['signal']])
                                        for t in base_rows[:5]])
        variants_detail[m] = detail
        print(f"[mode {m}] BASE={matrix['ledger'][m]['BASE']['total']:+,.0f} "
              f"V1={matrix['ledger'][m]['V1']['total']:+,.0f} V2={matrix['ledger'][m]['V2']['total']:+,.0f} "
              f"V2G={matrix['ledger'][m]['V2G']['total']:+,.0f} V2T1={matrix['ledger'][m]['V2T1']['total']:+,.0f} | "
              f"rep13 B/V/V2: {matrix['replay_cap13'][m]['BASE']['total_merged']:+,.0f}/"
              f"{matrix['replay_cap13'][m]['V1']['total_merged']:+,.0f}/"
              f"{matrix['replay_cap13'][m]['V2']['total_merged']:+,.0f}", flush=True)

    with open(os.path.join(OUT_DIR, 'cc_selection.json'), 'w') as f:
        json.dump(dict(meta=dict(generated_at=eng.gen_at), modes=selection_out), f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, 'cc_variants.json'), 'w') as f:
        json.dump(dict(meta=dict(generated_at=eng.gen_at, note='亏损单延长逐笔明细'), modes=variants_detail),
                  f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, 'cc_matrix.json'), 'w') as f:
        json.dump(matrix, f, ensure_ascii=False, indent=1)
    print('saved cc_selection/cc_variants/cc_matrix json')


if __name__ == '__main__':
    main()
