# -*- coding: utf-8 -*-
"""二轮挖掘 Equity Curve 族过滤 v2(2026-08-22)。
方法来源:method-survey A1/A7。v1 教训:逐笔已实现序列判定存在「停机死锁」(停机后无新平仓笔,
连亏/低于MA状态永不解冻,v1 结果 blocked 1119/1126 即此 bug 表现,已废弃)。
v2 业界标准实现:
  - 净值曲线 = 已平仓笔累积 pnl 的日度阶梯序列(空仓日平坦);MA 随时间回落可自然解冻;
  - consec/ddstop 类硬停规则配 20 交易日 probe 试探机制(停满 20 个交易日放行 1 笔,贴近实战降频观察);
规则族:
  eqma_d{20,60,120,250} : 净值 < 其 N 日简单均线 -> 停(纯 MA 法天然解冻,无需 probe)
  ddstop_{3k,5k,8k}     : 净值距历史峰值回撤超 X 元 -> 停 + probe20
  consec{3,5}           : 连续亏损 S 笔 -> 停 + probe20
输出:data/mine12_equity.json
复现:python3 mine12_equity.py
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R

OUT_PATH = os.path.join(BASE, 'data', 'mine12_equity.json')
PROBE_GAP = 20  # 交易日

def load_cal():
    """交易日轴(hs300 ohlc 日期,2010 起)。"""
    p = os.path.join(R._ROOT, 'static-site/data/index/hs300-all.json')
    return [o['date'] for o in json.load(open(p))['ohlc']]

def eval_equity_v2(rows, kind, param, cal, K=1):
    bydate = {}
    for t in rows:
        bydate.setdefault(str(t[0] or ''), []).append(t)
    cal_idx = {d: i for i, d in enumerate(cal)}
    days = [d for d in cal if d in bydate or True]  # 全日历扫描
    sel = []
    settled = {}
    cum = []          # 日度净值(已实现累计)
    cur_cum = 0.0
    peak = 0.0
    recent_closed = []  # 已结算 pnl 序列(供 consec)
    pending_probe_since = None
    last_action_idx = None
    for d in days:
        # 结算到期持仓
        for t in sel:
            bk = R.base_key(t, R.FIDX_GLOBAL)
            if bk in settled: continue
            sld = str(t[4] or '')
            if sld and sld <= d:
                settled[bk] = True
                cur_cum += t[R.IDX_PNL]['pnlYuan']
                recent_closed.append(t[R.IDX_PNL]['pnlYuan'])
        cum.append(cur_cum)
        peak = max(peak, cur_cum)
        i = cal_idx[d]
        # 判定
        if kind == 'eqma':
            N = param
            window = cum[-N:]
            ma = sum(window) / len(window)
            ok = len(cum) < N or cur_cum >= ma - 1e-6  # 容差防浮点卡死(v2.1 教训: 平台期 MA==cum 因 1e-12 浮点误差永不解冻)
        elif kind == 'ddstop':
            ok = (peak - cur_cum) < param
        elif kind == 'consec':
            cnt = 0
            for v in reversed(recent_closed):
                if v < 0: cnt += 1
                else: break
            ok = cnt < param
        else:
            raise ValueError(kind)
        if not ok and kind != 'eqma' and last_action_idx is not None \
           and i - last_action_idx >= PROBE_GAP and bydate.get(d):
            ok = True  # probe 放行
        if bydate.get(d):
            if ok:
                grp = sorted(bydate[d], key=lambda t: t[R.IDX_SKEY])
                sel.extend(grp[:K])
                last_action_idx = i
            else:
                last_action_idx = last_action_idx  # 停机不重置 probe 计时起点?重置才对
                # 设计:probe 计时从「上次任何决策日」起算;这里保持首次进入停机的时点
    return sel

def main():
    rows, fIdx = R.prepare_rows()
    R.init(rows, fIdx)
    base = R.eval_baseline(rows, 1)
    cal = load_cal()
    results = []
    grid = ([('eqma', n) for n in (20, 60, 120, 250)] +
            [('ddstop', x) for x in (3000, 5000, 8000)] +
            [('consec', s) for s in (3, 5)])
    for kind, param in grid:
        new_sel = eval_equity_v2(rows, kind, param, cal, 1)
        det = R.diff_detail(base, new_sel)
        gates = R.three_gates(base, new_sel, det)
        st_new = R.stats_of(new_sel)
        results.append(dict(kind=f'{kind}{param}', fill=dict(det, new_total=st_new['total']),
                            gates=gates, yearly_new=R.yearly_buckets(new_sel)))
        g = gates
        print(f"{kind}{param:<5d} net={det['net_improve']:+8.0f} blk({det['blocked_n']:>4d},{det['blocked_pnl']:+8.0f}) "
              f"add({det['added_n']:>3d},{det['added_pnl']:+7.0f}) | aprH={g['apr_hurt']:+7.0f} maA={g['mayaug_improve']:+7.0f} "
              f"fwd={g['forward']['net_improve']:+8.0f} nr={g['blocked_neg_ratio']:.0%} | "
              f"G{'1' if g['g1'] else '-'}{'2' if g['g2'] else '-'}{'3' if g['g3'] else '-'} newTotal={st_new['total']:.0f}")
    with open(OUT_PATH, 'w') as f:
        json.dump(dict(baseline=R.stats_of(base), rules=results), f, ensure_ascii=False)

if __name__ == '__main__':
    main()
