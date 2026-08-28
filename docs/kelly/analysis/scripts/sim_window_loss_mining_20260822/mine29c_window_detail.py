# -*- coding: utf-8 -*-
"""
mine29c: 「NEW14+剔 has_track/none」分窗口全维度细节版(回应用户质疑:近1/3/5年亏+近10年微正,全历史合计变差疑被远古正贡献掩盖)
目的: 分窗口(y1/y3/y5/y10/all)×双基座(NEW14/八键)给出剔除净效应全细节, 17笔逐笔明细+费率分解+替补映射+y5专项
      +bootstrap按窗+删笔不补位对照(用户直觉口径)+expanding时变规则演示(防前视)。
方法口径(与 mine29 完全一致):
  - 基座: NEW14 = build_mode_pool(tr,fIdx,'A') → finish_pool → hits_on(NEW14_KEYS) 黑名单; 八键 = prepare_rows()(mode A + 8键预过滤池)
  - 剔除规则: 黑名单 ∪ {has_track(track_tier=='none') 且 buy_date >= cutoff}(窗口=页面 period_cutoffs, 按 buy_date 落窗与前端一致)
  - 选择层: ev_new_on K=1 每日补位 top-K 前过滤(补位口径铁律); 删笔不补位为对照附注(资金闲置理想口径)
  - 费率双口径: ①页面口径 etf_main(万0.5/min0.1/滑点千1/沪过户万0.1)=lab.js L7009 _kellyRecomputeTrade 复刻(还原收盘价 bp/1.001→重加新滑点), 每笔固定1万;
               ②etf_def 费后(calc_row 万3/min5, mine29 主口径)对照
  - 毛利/费率分解: shares0=AMT/closeBuy; profit0=shares0*closeSell-AMT; fee=profit0-pNew(与 lab.js feeCost 同式)
输入依赖: static-site/data/signal_kelly_trades.json + data/mine10_features.json + data/mine24_compare.json
输出: data/mine29c_window_detail.json
复现命令: cd docs/kelly/analysis/scripts/sim_window_loss_mining_20260822 && python3 mine29c_window_detail.py
数据截止: 交易 buy_date 末日 2026-08-20(trades generated_at=2026-08-23 21:15)
关键口径一句话: mode A 权威锚点池 × {NEW14/八键} × 窗内 has_track/none 整组剔除黑名单 → ev_new_on K1 补位选择 → 双费率口径分窗分解。
"""
import os, sys, json, random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r2_common as R
from sim_core import load, build_mode_pool, base_key, calc_row
from mine18_detail import FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2
import mine25_longline_operable as M25
import mine27_g_exhaustive_simplified as M27

ROOT = '/Users/linhuichen/code/trade'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'mine29c_window_detail.json')
AMT = 10000.0
ORIG_SLIP = 0.001
FP_PAGE = dict(c=0.00005, minC=0.1, s=0.001, sh=0.00001, stamp=0.0)   # etf_main 页面默认档
WINDOWS = [('y1', None), ('y3', None), ('y5', None), ('y10', None), ('all', 'ALL')]

def is_sh(c): return str(c or '').startswith('51') or str(c or '').startswith('58')

def page_recompute(t, fIdx):
    """复刻 lab.js _kellyRecomputeTrade(etf_main 默认档, fixed 1万): 返回 (净利, 零费毛利, 费用, return_pct)"""
    bp = t[fIdx['buy_price']] or 0; sp = t[fIdx['sell_price']] or 0; cp = t[fIdx['current_price']] or 0
    ec = str(t[fIdx['etf_code']]); sd = t[fIdx['sell_date']]
    if bp <= 0: return 0.0, 0.0, 0.0, 0.0
    closeBuy = bp / (1 + ORIG_SLIP); closeSell = (sp / (1 - ORIG_SLIP)) if sd else cp
    c, s, minC = FP_PAGE['c'], FP_PAGE['s'], FP_PAGE['minC']
    sh = FP_PAGE['sh'] if is_sh(ec) else 0.0
    bpn = closeBuy * (1 + s)
    sh_n = AMT / (bpn * (1 + c + sh)); cb = sh_n * bpn * c
    if cb < minC: sh_n = (AMT - minC) / (bpn * (1 + sh))
    spn = closeSell * (1 - s); sa = sh_n * spn
    p = sa - max(sa * c, minC) - sa * sh - sa * FP_PAGE['stamp'] - AMT
    shares0 = AMT / closeBuy
    p0 = shares0 * closeSell - AMT          # 零费毛利
    return p, p0, p0 - p, p / AMT * 100

def def_fee(t, fIdx):
    """etf_def 费后(mine29 主口径) + 其费用额"""
    r = calc_row(t, fIdx)
    return r['pnlYuan'], r['buyFee'] + r['sellFee']

def main():
    tr, fIdx = load(os.path.join(ROOT, 'static-site/data/signal_kelly_trades.json'))
    cuts = tr['period_cutoffs']
    FEATS = json.load(open(FEATS_PATH))
    M24CMP = json.load(open(M25.M24CMP_PATH))
    NEW14_KEYS = list(M24CMP['new_keys'])
    rules = build_rules(FEATS, fIdx); rules.update(build_r2(fIdx))
    base = len(fIdx)

    # ---- 锚点复现(必过) ----
    pool_raw = M27.finish_pool(build_mode_pool(tr, fIdx, 'A'), fIdx)
    R.init(pool_raw, fIdx)
    rows8, fia = R.prepare_rows()
    R.init(rows8, fia)
    rules8 = build_rules(FEATS, fia); rules8.update(build_r2(fia))
    blkN14 = M25.hits_on(pool_raw, fIdx, NEW14_KEYS, rules)
    selN14 = M25.ev_new_on(pool_raw, fIdx, blkN14)
    stN = R.stats_of(selN14)
    assert abs(stN['total'] - 122648.33) < 1.0, stN['total']
    ctx8 = M25.build_ctx(rows8, fia)
    st8 = R.stats_of(M25.ev(ctx8, (), False))
    assert abs(st8['total'] - 66530.38) < 0.5, st8['total']
    print(f"锚点 PASS: NEW14={stN['total']:+,.2f} P0_8键={st8['total']:+,.2f}")

    bq_all = {base_key(t, fIdx) for t in pool_raw if str(t[fIdx['track_tier']] or '') == 'none'}
    bq8_all = {base_key(t, fia) for t in rows8 if str(t[fia['track_tier']] or '') == 'none'}
    ks_baseN = {base_key(t, fIdx) for t in selN14}

    win_list = [(k, cuts[k]) for k in ['y1', 'y3', 'y5', 'y10']] + [('all', '0')]
    out_windows = []

    for wname, cut in win_list:
        row = dict(window=wname, cutoff=(cut if cut != '0' else '全历史'))
        for tag, pool, fi, blk, bqset in [('NEW14', pool_raw, fIdx, blkN14, bq_all),
                                          ('八键', rows8, fia, set(), bq8_all)]:
            R.init(pool, fi)
            base_sel = selN14 if tag == 'NEW14' else M25.ev(ctx8, (), False)
            blk_c = set(blk) | {k for k in bqset}
            if cut != '0':
                # 只剔窗口内(buy_date>=cutoff)的该组信号
                win_keys = {base_key(t, fi) for t in pool
                            if base_key(t, fi) in bqset and str(t[fi['buy_date']]) >= cut}
            else:
                win_keys = set(bqset)
            drop_sel = M25.ev_new_on(pool, fi, blk_c | win_keys) if tag == 'NEW14' else M25.ev_new_on(pool, fi, win_keys)
            ks_d = {base_key(t, fi) for t in drop_sel}
            dropped = [t for t in base_sel if base_key(t, fi) not in ks_d and base_key(t, fi) in win_keys]
            ks_b = {base_key(t, fi) for t in base_sel}
            added = [t for t in drop_sel if base_key(t, fi) not in ks_b]
            # 补位口径 Δ(页面口径)
            d_page = [page_recompute(t, fi) for t in dropped]
            a_page = [page_recompute(t, fi) for t in added]
            d_def = [def_fee(t, fi) for t in dropped]
            a_def = [def_fee(t, fi) for t in added]
            delta_page = -sum(x[0] for x in d_page) + sum(x[0] for x in a_page)
            delta_def = -sum(x[0] for x in d_def) + sum(x[0] for x in a_def)
            # 删笔不补位对照(用户直觉口径: 剔除后资金闲置)
            dnfp_page = -sum(x[0] for x in d_page)
            dnfp_def = -sum(x[0] for x in d_def)
            row[tag] = dict(
                cutoff=cut,
                dropped=dict(
                    n=len(dropped),
                    gross_page=round(sum(x[1] for x in d_page), 2),
                    fee_page=round(sum(x[2] for x in d_page), 2),
                    net_page=round(sum(x[0] for x in d_page), 2),
                    net_def=round(sum(x[0] for x in d_def), 2),
                    fee_def=round(sum(x[1] for x in d_def), 2)),
                added=dict(
                    n=len(added),
                    gross_page=round(sum(x[1] for x in a_page), 2),
                    fee_page=round(sum(x[2] for x in a_page), 2),
                    net_page=round(sum(x[0] for x in a_page), 2),
                    net_def=round(sum(x[0] for x in a_def), 2)),
                delta_fill_page=round(delta_page, 2),
                delta_fill_def=round(delta_def, 2),
                delta_nofill_page=round(dnfp_page, 2),
                delta_nofill_def=round(dnfp_def, 2))
        out_windows.append(row)
        print(f"[{wname}] NEW14: 被剔{row['NEW14']['dropped']['n']}笔/净{row['NEW14']['dropped']['net_page']:+,.0f} "
              f"替补{row['NEW14']['added']['n']}笔/{row['NEW14']['added']['net_page']:+,.0f} "
              f"Δ补位{row['NEW14']['delta_fill_page']:+,.2f} Δ不补{row['NEW14']['delta_nofill_page']:+,.2f} | "
              f"八键Δ补位{row['八键']['delta_fill_page']:+,.2f}")

    # ---- 17 笔逐笔明细(NEW14 全历史) ----
    detail17 = []
    added_all = None
    # 重算 all 窗的 added(NEW14 基座)
    drop_sel_all = M25.ev_new_on(pool_raw, fIdx, blkN14 | bq_all)
    ks_da = {base_key(t, fIdx) for t in drop_sel_all}
    added_all = [t for t in drop_sel_all if base_key(t, fIdx) not in ks_baseN]
    a_add = [page_recompute(t, fIdx) for t in added_all]
    for t in sorted(selN14, key=lambda x: str(x[fIdx['signal_date']])):
        k = base_key(t, fIdx)
        if k not in bq_all: continue
        p, g, fee, rp = page_recompute(t, fIdx)
        pd_, pf = def_fee(t, fIdx)
        bd = str(t[fIdx['buy_date']]); sd_ = str(t[fIdx['sell_date']] or '')
        hd = t[fIdx['hold_days']]
        win = 'y1' if bd >= cuts['y1'] else 'y3' if bd >= cuts['y3'] else 'y5' if bd >= cuts['y5'] else 'y10'
        detail17.append(dict(
            signal_date=str(t[fIdx['signal_date']]), index=t[fIdx['index_id']], signal=t[fIdx['signal']],
            etf=f"{t[fIdx['etf_code']]} {t[fIdx['etf_name']]}", track_score=t[fIdx['track_score']],
            buy_date=bd, sell_date=sd_, hold_days=hd,
            buy_price=round(float(t[fIdx['buy_price']]), 4), sell_price=(round(float(t[fIdx['sell_price']]), 4) if sd_ else None),
            window=win,
            gross_page=round(g, 2), fee_page=round(fee, 2), net_page=round(p, 2),
            net_def=round(pd_, 2), fee_def=round(pf, 2)))
    print(f"17笔明细: 毛利{sum(d['gross_page'] for d in detail17):+,.2f} 费率{sum(d['fee_page'] for d in detail17):+,.2f} 净{sum(d['net_page'] for d in detail17):+,.2f}")

    # ---- y5 12笔专项: A/H 模式构成 ----
    y5cut = cuts['y5']
    spec_y5 = {}
    S_SET = set(json.load(open('/tmp/mine29_surv_keys.json'))) if os.path.exists('/tmp/mine29_surv_keys.json') else None
    modemapA = {}
    for m in 'ABCDEFGHI':
        mm = {}
        for qk in tr['quadrants']:
            for t in (tr['quadrants'][qk].get(m) or []):
                kk = base_key(t, fIdx)
                if kk in ks_baseN and kk in bq_all and str(t[fIdx['buy_date']]) >= y5cut and kk not in mm:
                    mm[kk] = t
        modemapA[m] = [v for v in mm.values() if str(v[fIdx['buy_date']]) >= y5cut]
    for m in 'ABCDEFGHI':
        ts = modemapA[m]
        rows = [page_recompute(t, fIdx)[0] for t in ts]
        spec_y5[m] = dict(n=len(ts), net_page=round(sum(rows), 2),
                          per_trade=[round(x, 2) for x in rows])
    print('y5 各模式净利:', {m: spec_y5[m]['net_page'] for m in 'ABCDEFGHI'})

    # ---- bootstrap 按窗(NEW14 基座, 页面口径 Δ 的不确定性) ----
    rng = random.Random(29)
    boot = []
    for wname, cut in win_list:
        blk_c = set(blkN14) | bq_all
        if cut != '0':
            win_keys = {base_key(t, fIdx) for t in pool_raw
                        if base_key(t, fIdx) in bq_all and str(t[fIdx['buy_date']]) >= cut}
        else:
            win_keys = set(bq_all)
        drop_sel = M25.ev_new_on(pool_raw, fIdx, blk_c | win_keys)
        ks_d = {base_key(t, fIdx) for t in drop_sel}
        dropped = [t for t in selN14 if base_key(t, fIdx) not in ks_d and base_key(t, fIdx) in win_keys]
        ks_b = ks_baseN
        added = [t for t in drop_sel if base_key(t, fIdx) not in ks_b]
        dp = [page_recompute(t, fIdx)[0] for t in dropped]
        ap = [page_recompute(t, fIdx)[0] for t in added]
        deltas = []
        for _ in range(9999):
            ds = sum(rng.choice(dp) for _ in range(len(dp))) if dp else 0.0
            as_ = sum(rng.choice(ap) for _ in range(len(ap))) if ap else 0.0
            deltas.append(-ds + as_)
        deltas.sort()
        boot.append(dict(window=wname, blocked_n=len(dp), added_n=len(ap),
                         observed_delta=round(-sum(dp) + sum(ap), 2),
                         ci95=[round(deltas[int(0.025 * 9999)], 2), round(deltas[int(0.975 * 9999)], 2)],
                         contains_zero=deltas[int(0.025 * 9999)] <= 0 <= deltas[int(0.975 * 9999)]))
        print(f"[boot {wname}] 被剔{len(dp)} 替补{len(ap)} 观测Δ={boot[-1]['observed_delta']:+,.2f} CI95={boot[-1]['ci95']}")

    # ---- expanding 时变规则演示(防前视): 该组最近8笔已实现净利<0 → 暂停该组新信号, 直到转正 ----
    hist = {}   # base_key -> (buy_date, sell_date_or_'', net_page)
    for t in selN14:
        k = base_key(t, fIdx)
        if k in bq_all:
            p = page_recompute(t, fIdx)[0]
            hist[k] = (str(t[fIdx['buy_date']]), str(t[fIdx['sell_date']] or ''), p)
    dyn_blk = set()
    seq = sorted(hist.items(), key=lambda kv: kv[1][0])
    realized = []   # 已实现(sell_date 非空且 sell < 当前 buy)
    for k, (bd, sd, p) in seq:
        realized = [x for x in realized if x[0] and x[0] < bd]
        recent = sorted(realized, key=lambda x: x[0])[-8:]
        if len(recent) >= 3 and sum(x[1] for x in recent) < 0:
            dyn_blk.add(k)
        else:
            if sd: realized.append((sd, p))
    selDyn = M25.ev_new_on(pool_raw, fIdx, blkN14 | dyn_blk)
    ks_dyn = {base_key(t, fIdx) for t in selDyn}
    dyn_blocked = [t for t in selN14 if base_key(t, fIdx) not in ks_dyn]
    dyn_added = [t for t in selDyn if base_key(t, fIdx) not in ks_baseN]
    dbp = [page_recompute(t, fIdx) for t in dyn_blocked]
    dap = [page_recompute(t, fIdx) for t in dyn_added]
    dyn_delta = -sum(x[0] for x in dbp) + sum(x[0] for x in dap)
    print(f"[expanding演示] 动态拦{len(dyn_blocked)}笔/{sum(x[0] for x in dbp):+,.2f} 替补{len(dyn_added)}笔/{sum(x[0] for x in dap):+,.2f} Δ={dyn_delta:+,.2f}")

    out = dict(
        meta=dict(script='mine29c_window_detail.py', date='2026-08-24',
                  data='signal_kelly_trades.json generated_at=' + str(tr.get('generated_at')),
                  caliber='mode A 权威锚点池 × {NEW14/八键} × 窗内 track_tier==none 整组剔除 → ev_new_on K1 补位 + 删笔不补位对照; 费率双口径(页面etf_main主/etf_def对照); 窗口归属=buy_date>=cutoff(与前端一致)',
                      anchors=dict(NEW14=stN['total'], P0_8key=st8['total'])),
        windows=out_windows,
        detail17=detail17,
        detail17_added=[dict(signal_date=str(t[fIdx['signal_date']]), index=t[fIdx['index_id']], signal=t[fIdx['signal']],
                             etf=f"{t[fIdx['etf_code']]} {t[fIdx['etf_name']]}",
                             buy_date=str(t[fIdx['buy_date']]),
                             gross_page=round(page_recompute(t, fIdx)[1], 2),
                             fee_page=round(page_recompute(t, fIdx)[2], 2),
                             net_page=round(page_recompute(t, fIdx)[0], 2)) for t in added_all],
        spec_y5_by_mode=spec_y5,
        bootstrap_by_window=boot,
        expanding_demo=dict(rule='该组(NEW14幸存∩track_tier==none)最近已实现≤8笔累计净利<0(至少3笔)→暂停该组新买入,转正自动恢复;纯后视数据,无未来信息',
                            blocked_n=len(dyn_blocked), blocked_net_page=round(sum(x[0] for x in dbp), 2),
                            added_n=len(dyn_added), added_net_page=round(sum(x[0] for x in dap), 2),
                            delta_page=round(dyn_delta, 2),
                            blocked_list=[dict(date=str(t[fIdx['buy_date']]), etf=t[fIdx['etf_name']],
                                               net=round(page_recompute(t, fIdx)[0], 2)) for t in dyn_blocked]))
    with open(OUT, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('已写', OUT)

if __name__ == '__main__':
    main()
