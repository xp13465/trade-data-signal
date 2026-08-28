# -*- coding: utf-8 -*-
"""固定持有天数穷举回测: 5/10/15/20/30/40/50天 × S06/A/NEW14+1 三模式全矩阵。
"""
import os, sys, json, bisect, sqlite3, datetime

REPO = '/Users/linhuichen/code/trade'
M21 = os.path.join(REPO, 'docs/kelly/analysis/scripts/sim_window_loss_mining_20260822')
sys.path.insert(0, M21)
sys.path.insert(0, REPO)

from sim_core import (load, build_mode_pool, passes_fade, DEFAULT_FILTERS,
                      active_month_mask, PRIN, base_key, calc_row, buy_with_fees, sell_with_fees, FP_DEF)
import r2_common as R
import mine27_g_exhaustive_simplified as M27

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_JSON = os.path.join(REPO, 'static-site/data/signal_kelly_trades.json')
S06_JSON = os.path.join(REPO, 'static-site/data/kelly_mode_s06_state.json')
FEATS_PATH = os.path.join(M21, 'data/mine10_features.json')
ETF_DB_CANDIDATES = [os.path.join(os.path.dirname(REPO), 'trade-data/data/etf_national_team.db'),
                     os.path.join(REPO, 'data/etf_national_team.db')]

HOLD_DAYS_LIST = [5, 10, 15, 20, 30, 40, 50]
CAP_MAIN = 13
A_SUB = ('T1', 'Q1', 'M1', 'V1', 'R1', 'R2a', 'R2b', 'R2g')


def ro(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def c1_hit(t, fi):
    return t[fi['signal']] in ('buy_aux', 'buy_backup') and (t[fi['market_tier']] or '') == '牛市·主升'


def x1_hit(t, fi):
    v = t[fi['track_tier']]
    return v is None or str(v) == 'none'


class SweepEngine:
    def __init__(self):
        self.tr, self.fi = load(TRADES_JSON)
        self.gen_at = self.tr.get('generated_at')
        self.pool = build_mode_pool(self.tr, self.fi, 'A')
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
        fi = self.fi
        out = []
        if mode == 'a9':
            for sd in sorted(self.g_8):
                for t in self.g_8[sd]:
                    if base_key(t, fi) not in self.a9_extra_blk:
                        out.append(t)
                        break
            return out
        if mode == 'new15':
            blk = self.new14_blk | self.x1_blk
            for sd in sorted(self.g_all):
                for t in self.g_all[sd]:
                    if base_key(t, fi) not in blk:
                        out.append(t)
                        break
            return out
        if mode == 's06':
            a9_blk = self.a9_extra_blk
            n15_blk = self.new14_blk | self.x1_blk
            for sd in sorted(self.g_all):
                b = self.s06_daily.get(sd, self.s06_off)
                if b == self.s06_on:
                    grp = self.g_8.get(sd, [])
                    for t in grp:
                        if base_key(t, fi) not in a9_blk:
                            out.append(t)
                            break
                else:
                    for t in self.g_all[sd]:
                        if base_key(t, fi) not in n15_blk:
                            out.append(t)
                            break
            return out
        raise ValueError(mode)


def load_prices(codes):
    nav = {}
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
    conn.close()
    for c in nav:
        sdates[c] = sorted(nav[c].keys())
    return nav, sdates


def backtest_fixed_day(t, fi, nav, sdates, hold_days, today_str):
    signal_date = str(t[fi['signal_date']])
    etf_code = t[fi['etf_code']]
    buy_price = float(t[fi['buy_price']] or 0)
    if buy_price <= 0 or not etf_code:
        return None
    ds = sdates.get(etf_code, [])
    if not ds:
        return None
    br = buy_with_fees(PRIN, buy_price, etf_code, FP_DEF)
    shares = br['shares']
    if shares <= 0:
        return None
    idx = bisect.bisect_right(ds, signal_date)
    future_dates = ds[idx:idx + hold_days]
    if len(future_dates) < hold_days:
        ref = today_str
        nv = nav.get(etf_code, {}).get(ref)
        if nv is None and ds:
            nv = nav.get(etf_code, {}).get(ds[-1])
            ref = ds[-1]
        if nv is None or nv <= 0:
            return None
        sr = sell_with_fees(shares, nv, etf_code, FP_DEF)
        pnl = sr['net'] - PRIN
        return dict(signal_date=signal_date, buy_date=signal_date, sell_date='',
                    etf_code=etf_code, pnl=pnl, is_holding=True, hold_days_actual=0)
    sell_date = future_dates[-1]
    nv = nav.get(etf_code, {}).get(sell_date)
    if nv is None or nv <= 0:
        return None
    sr = sell_with_fees(shares, nv, etf_code, FP_DEF)
    pnl = sr['net'] - PRIN
    return dict(signal_date=signal_date, buy_date=signal_date, sell_date=sell_date,
                etf_code=etf_code, pnl=pnl, is_holding=False, hold_days_actual=len(future_dates))


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


def ledger_stats(results):
    realized = [r for r in results if not r['is_holding']]
    bys = {}
    for r in realized:
        bys[r['sell_date']] = bys.get(r['sell_date'], 0.0) + r['pnl']
    mdd, trough = dd_of(bys)
    n = len(results)
    win = sum(1 for r in results if r['pnl'] > 0)
    tot = sum(r['pnl'] for r in results)
    tot_r = sum(r['pnl'] for r in realized)
    return dict(n=n, total=round(tot, 2), total_realized=round(tot_r, 2),
                n_realized=len(realized), n_censored=n - len(realized),
                win_rate_pct=round(win / max(n, 1) * 100, 1),
                mdd_realized=mdd, mdd_trough=trough)


def peak_concurrent(results):
    events = []
    for r in results:
        events.append((r['buy_date'], 0))
        events.append((r['sell_date'] if r['sell_date'] else '99999999', 1))
    events.sort()
    cur = mx = 0
    for _, etype in events:
        if etype == 0:
            cur += 1
            mx = max(mx, cur)
        else:
            cur -= 1
    return mx


def main():
    print("=" * 70)
    print("固定持有天数穷举回测: 5/10/15/20/30/40/50天 × S06/A/NEW14+1")
    print("=" * 70)

    eng = SweepEngine()
    fi = eng.fi
    print(f"数据: generated_at={eng.gen_at}  池={len(eng.pool)}笔")

    codes = sorted({t[fi['etf_code']] for t in eng.pool})
    print(f"加载 {len(codes)} ETF 价格...")
    nav, sdates = load_prices(codes)
    today_str = max((ds[-1] for ds in sdates.values() if ds), default=None)
    print(f"价格最新: {today_str}")

    modes = {'s06': 'S06', 'a9': 'A(on9)', 'new15': 'NEW14+1'}
    sels = {}
    for m in modes:
        sels[m] = eng.select(m)
        print(f"  {modes[m]}: {len(sels[m])}笔")

    # 全矩阵
    matrix = {}
    for hd in HOLD_DAYS_LIST:
        matrix[hd] = {}
        for m in modes:
            results = []
            for t in sels[m]:
                r = backtest_fixed_day(t, fi, nav, sdates, hd, today_str)
                if r is not None:
                    results.append(r)
            ledger = ledger_stats(results)
            pk = peak_concurrent(results)

            # cap13 replay: 需要构建 replay 格式
            replay_rows = {}
            for r in results:
                sd = r['signal_date']
                if sd in replay_rows:
                    continue  # 每信号日取第一个
                # 构造一个 mock trade row 给 replay3
                row = [sd, '', r.get('signal', ''), r['buy_date'], r['sell_date'],
                       r['etf_code'], '', '', '', '', '', 0, 0, 0, 0, 0,
                       hd, '', 0, '', '', '', '', '']
                row[R.IDX_PNL] = dict(pnlYuan=r['pnl'], isHolding=r['is_holding'],
                                       pnlPct=r['pnl'] / PRIN * 100, buyFee=0, sellFee=0)
                row[R.IDX_SKEY] = sd
                replay_rows[sd] = row

            try:
                rp = M27.replay3(replay_rows, fi, CAP_MAIN, 'v2回补极简')
                span_years = 12.0
                near_cut = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y%m%d')
                st = M27.stats_ext(rp, fi, CAP_MAIN, CAP_MAIN * PRIN, span_years, near_cut)
                r13 = st.get('total_merged', 0)
                skip_n = st.get('n_skipped', 0)
                mdd_m = st.get('mdd_merged_terminal', {})
                if isinstance(mdd_m, dict):
                    mdd_m = mdd_m.get('mdd', 0)
            except Exception as ex:
                r13 = 0
                skip_n = 0
                mdd_m = 0

            yearly = {}
            for r in results:
                y = r['signal_date'][:4]
                yearly.setdefault(y, 0.0)
                yearly[y] += r['pnl']

            matrix[hd][m] = dict(
                ledger=ledger, replay_cap13=round(r13, 2), skip=skip_n,
                peak=pk, peak_yuan=pk * PRIN,
                mdd_merged=round(mdd_m, 2) if isinstance(mdd_m, (int, float)) else 0,
                yearly={y: round(v, 2) for y, v in sorted(yearly.items())},
            )
            print(f"  HD={hd:2d} {modes[m]:10s}: 账本={ledger['total']:>+10,.0f}  "
                  f"cap13={r13:>+10,.0f}  峰={pk:2d}笔  skip={skip_n:4d}  "
                  f"mdd={ledger['mdd_realized']:>+8,.0f}  胜率={ledger['win_rate_pct']:.1f}%")

    # 保存
    out = dict(meta=dict(hold_days_list=HOLD_DAYS_LIST, modes=list(modes.keys()),
                         generated_at=eng.gen_at, today_str=today_str,
                         fee='FP_DEF PRIN=10000 K1', cap=CAP_MAIN),
               matrix=matrix)
    out_path = os.path.join(OUT_DIR, 'sweep_matrix.json')
    with open(out_path, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n保存: {out_path}")

    # 对比表
    print("\n" + "=" * 70)
    print("账本层净利(每笔1万)")
    print("=" * 70)
    print(f"{'HD':>4s}", end="")
    for m in modes:
        print(f"  {modes[m]:>12s}", end="")
    print()
    for hd in HOLD_DAYS_LIST:
        print(f"{hd:4d}", end="")
        for m in modes:
            print(f"  {matrix[hd][m]['ledger']['total']:>+12,.0f}", end="")
        print()

    print("\n--- cap13 组合层 ---")
    print(f"{'HD':>4s}", end="")
    for m in modes:
        print(f"  {modes[m]:>12s}", end="")
    print()
    for hd in HOLD_DAYS_LIST:
        print(f"{hd:4d}", end="")
        for m in modes:
            print(f"  {matrix[hd][m]['replay_cap13']:>+12,.0f}", end="")
        print()

    print("\n--- 峰值并发(笔, 20倍线=≤20合规) ---")
    print(f"{'HD':>4s}", end="")
    for m in modes:
        print(f"  {modes[m]:>12s}", end="")
    print()
    for hd in HOLD_DAYS_LIST:
        print(f"{hd:4d}", end="")
        for m in modes:
            pk = matrix[hd][m]['peak']
            tag = "OK" if pk <= 20 else "!!"
            print(f"  {pk:>10d}{tag}", end="")
        print()

    print("\n--- 最大回撤(MDD, 账本层) ---")
    print(f"{'HD':>4s}", end="")
    for m in modes:
        print(f"  {modes[m]:>12s}", end="")
    print()
    for hd in HOLD_DAYS_LIST:
        print(f"{hd:4d}", end="")
        for m in modes:
            print(f"  {matrix[hd][m]['ledger']['mdd_realized']:>+12,.0f}", end="")
        print()

    print("\n--- cap13 vs 基线(HD=10)净差 ---")
    print(f"{'HD':>4s}", end="")
    for m in modes:
        print(f"  {modes[m]:>12s}", end="")
    print()
    base10 = {m: matrix[10][m]['replay_cap13'] for m in modes}
    for hd in HOLD_DAYS_LIST:
        print(f"{hd:4d}", end="")
        for m in modes:
            diff = matrix[hd][m]['replay_cap13'] - base10[m]
            print(f"  {diff:>+12,.0f}", end="")
        print()

    print("\n--- 胜率 ---")
    print(f"{'HD':>4s}", end="")
    for m in modes:
        print(f"  {modes[m]:>12s}", end="")
    print()
    for hd in HOLD_DAYS_LIST:
        print(f"{hd:4d}", end="")
        for m in modes:
            print(f"  {matrix[hd][m]['ledger']['win_rate_pct']:>11.1f}%", end="")
        print()


if __name__ == '__main__':
    main()
