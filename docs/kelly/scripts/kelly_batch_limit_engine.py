#!/usr/bin/env python3
# 【次日分批挂单】核心引擎 (2026-08-15)
# 用途: 把"次日分N单挂开盘-1%限价"做成可回测引擎
#   成交规则: strict=True 只触达买(低<=限价); False 兜底(未触达按次日开盘买, 预算100%用满)
#   资金口径: daily_pool=每日1万等分(主口径) / fixed_1w=每笔固定1万(旧口径, 峰值不现实)
#   补单来源: none(不补) / pool(池内top-K剩余) / outside(降级top-K之外)
#   玩法变体: run_batch(基础兜底) / run_batch_full(完整玩法=严格优先+降级补+开盘兜底)
#             / run_batch_user(用户原话版=固定top-N额度+缺额补挂+兜底)
# 结论摘要: 兜底N=K是最优玩法: 每日池G K1净+86.1万(比次日开盘+6.1万), 收益率53.17%, 均价-0.374%
# 依赖: kelly_combo_advice_analysis / kelly_posfilter_backtest / kelly_ksens / kelly_dailypool
#       / scripts/simulate_trade.py; gap数据来自 trade-data/data/etf_national_team.db etf_daily 表
# 复现: python3 docs/kelly/scripts/kelly_batch_limit_engine.py
# 数据版本: static-site/data/signal_kelly_trades.json (8-15 00:45重新生成, G模式基笔7598)

"""次日分批挂单限价买入口径回测引擎 (穷举玩法矩阵)
玩法(用户原话): 次日不追开盘, 分N单挂"开盘-1%"限价, 总预算1w(每日池)不变;
  触达(当日low<=限价)按限价成交, 未触达: 严格=不买 / 兜底=按开盘价买;
  缺额补单(严格模式): 缺额从补单来源(池内top-K剩余 / 降级top-K之外)补挂, 补到满1w或品种用完。
价格: etf_daily open/low + accum_nav 等比例重定价(与 kelly_nextday_engine 一致)。
只读, 不改任何生产文件。
"""
import sys, json, sqlite3, math
from collections import defaultdict
sys.path.insert(0, '/tmp')
sys.path.insert(0, '/Users/linhuichen/code/trade/scripts')
from kelly_combo_advice_analysis import load, fIdx, passes_fade, empty_filters, BUY_AMOUNT
from kelly_posfilter_backtest import base_signals, base_key
from kelly_ksens import keep_topk, full_sort_key
from kelly_dailypool import DAILY, compute_scaled
from simulate_trade import _buy_with_fees, _sell_with_fees

# 份额折算伪跳空(底子报告 §1.4 识别): 非真实可交易, 基线与玩法同剔除
DROP_KEYS = {
    '20260731|csi_930851|buy_aux|20260731|159739',
    '20211111|thsc_300082|buy_special|20211111|512560',
}

def clean_base(mode):
    return [t for t in base_signals(mode) if base_key(t) not in DROP_KEYS]

# ---- GAP map: base_key -> {gap, next_date, low_ratio} (与 kelly_nextday_engine 同构) ----
def build_gap_map(mode='G'):
    G = clean_base(mode)
    DB = '/Users/linhuichen/code/trade-data/data/etf_national_team.db'
    conn = sqlite3.connect(DB); cur = conn.cursor()
    out = {}
    for t in G:
        sd = str(t[fIdx['signal_date']]); code = str(t[fIdx['etf_code']] or '')
        key = base_key(t)
        r = cur.execute('SELECT close FROM etf_daily WHERE etf_code=? AND date=?', (code, sd)).fetchone()
        if r is None or not r[0]:
            out[key] = None; continue
        close_sd = r[0]
        r2 = cur.execute('SELECT date, open, low FROM etf_daily WHERE etf_code=? AND date>? AND open IS NOT NULL AND low IS NOT NULL ORDER BY date ASC LIMIT 1', (code, sd)).fetchone()
        if r2 is None or not r2[1]:
            out[key] = None; continue
        nd, opn, lo = r2
        out[key] = {'gap': opn / close_sd, 'next_date': nd, 'low_ratio': lo / close_sd}
    conn.close()
    return out

GAP_CACHE = {}
def get_gap(mode='G'):
    if mode not in GAP_CACHE:
        GAP_CACHE[mode] = build_gap_map(mode)
    return GAP_CACHE[mode]

# ---- 单品种限价成交信息 ----
def buy_info(t, mode='G'):
    key = base_key(t)
    gi = get_gap(mode).get(key)
    if gi is None:
        return None
    bp = t[fIdx['buy_price']] or 0
    if bp <= 0:
        return None
    nav_sd = bp / 1.001
    return dict(key=key, code=str(t[fIdx['etf_code']] or ''),
                nav_sd=nav_sd, gap=gi['gap'], low_ratio=gi['low_ratio'],
                next_date=gi['next_date'], sell_date=str(t[fIdx['sell_date']] or ''),
                hold=max((t[fIdx['hold_days']] or 0) - 1, 0),
                sp=t[fIdx['sell_price']], cp=t[fIdx['current_price']])

def fill_trade(t, amount, limit_pct, strict, mode='G'):
    """在 t 上挂 开盘*(1-limit_pct) 限价单, 预算 amount。
    触达(低<=限价)→限价成交; 未触达→strict不买None / 兜底开盘成交。
    返回 (profit, rpct, amount_used, next_date, sell_date, hold, buy_ratio)"""
    info = buy_info(t, mode)
    if info is None:
        return None
    limit_ratio = info['gap'] * (1 - limit_pct)
    if info['low_ratio'] > 0 and info['low_ratio'] <= limit_ratio:
        ratio = limit_ratio
        touched = True
    else:
        if strict:
            return None
        ratio = info['gap']
        touched = False
    nav = info['nav_sd'] * ratio
    buy_price, shares, _c, _tf = _buy_with_fees(amount, nav, info['code'])
    if shares <= 0:
        return None
    if info['sp'] and info['sp'] > 0:
        nav_sell = info['sp'] / 0.999
        net = _sell_with_fees(shares, nav_sell, info['code'])[4]
    elif info['cp'] and info['cp'] > 0:
        net = _sell_with_fees(shares, info['cp'], info['code'])[4]
    else:
        return None
    profit = net - amount
    rpct = profit / amount * 100
    buy_ratio = ratio / info['gap']  # 买入价相对次日开盘价(触达=0.99, 兜底=1.0)
    return (profit, rpct, info['next_date'], info['sell_date'], info['hold'], amount, touched, buy_ratio)

# ---- 按日分批模拟 ----
def day_batch(day_rows, day_outside, N, limit_pct, strict, fill_source, per_slot_mode):
    """day_rows: 当日推荐(top-K过滤+toggle)已按 full_sort_key 排序
    day_outside: 降级补单来源(top-K之外, 过toggle)已排序
    N: 初始挂单数; per_slot_mode: 'daily_pool'/'fixed_1w'
    fill_source: 'none'/'pool'/'outside'
    每日池口径: 每单预算 = 10000/实际挂单数(预算恒用满, 除非品种不足)
    每笔固定口径: 每单 = 10000(预算 = 挂单数*1万)
    返回 (items, stats_summary)"""
    M = len(day_rows)
    init_n = min(N, M)
    if per_slot_mode == 'daily_pool':
        per_slot = 10000.0 / init_n if init_n else 0.0
        total_budget = 10000.0
    else:
        per_slot = 10000.0
        total_budget = 10000.0 * init_n
    results = []
    used_amt = 0.0
    n_touched = 0
    n_buy = 0
    disc_sum = 0.0
    disc_amt = 0.0
    any_touch = False
    # 初始单
    for i in range(init_n):
        t = day_rows[i]
        r = fill_trade(t, per_slot, limit_pct, strict, mode=cur_mode)
        if r is not None:
            results.append(r[:6])
            used_amt += r[5]
            n_buy += 1
            if r[6]:
                n_touched += 1
                any_touch = True
            disc_sum += r[7] * r[5]
            disc_amt += r[5]
    # 补单(仅严格模式)
    if strict and fill_source != 'none':
        if fill_source == 'pool':
            cand = day_rows[init_n:]
        elif fill_source == 'outside':
            cand = day_outside
        else:
            cand = []
        for t in cand:
            remaining = total_budget - used_amt
            if remaining <= 0.01:
                break
            amt = min(per_slot, remaining)
            r = fill_trade(t, amt, limit_pct, strict, mode=cur_mode)
            if r is not None:
                results.append(r[:6])
                used_amt += r[5]
                n_buy += 1
                if r[6]:
                    n_touched += 1
                    any_touch = True
                disc_sum += r[7] * r[5]
                disc_amt += r[5]
    return results, dict(total_budget=total_budget, used=used_amt, n_buy=n_buy,
                         n_touched=n_touched, n_sig=M, n_out=len(day_outside),
                         disc_sum=disc_sum, disc_amt=disc_amt, any_touch=any_touch)

cur_mode = 'G'  # 全局模式(供 fill_trade)

# ---- 口径主入口 ----
def build_day_pool(mode, keep, F):
    """返回 {sd: (day_rows_sorted, day_outside_sorted)}"""
    get_gap(mode)
    global cur_mode; cur_mode = mode
    bd = defaultdict(list)
    for t in clean_base(mode):
        if F is not None and not passes_fade(t, F):
            continue
        bd[str(t[fIdx['signal_date']])].append(t)
    out = {}
    keep_set = keep if keep is not None else None
    for sd, rows in bd.items():
        if keep_set is not None:
            rows_in = [r for r in rows if base_key(r) in keep_set]
            rows_out = [r for r in rows if base_key(r) not in keep_set]
        else:
            rows_in = rows
            rows_out = []
        rows_in.sort(key=full_sort_key)
        rows_out.sort(key=full_sort_key)
        if rows_in:
            out[sd] = (rows_in, rows_out)
    return out

def run_batch(mode='G', keep=None, F=None, N=2, limit_pct=0.01, strict=True,
              fill_source='none', amount_mode='daily_pool'):
    """amount_mode: 'daily_pool' 每日池1w等分(per_slot=10000/N) / 'fixed_1w' 每笔固定1万(per_slot=10000)
    返回 (items, day_stats_summary)"""
    day_pool = build_day_pool(mode, keep, F)
    items = []
    stats = []
    for sd, (rows_in, rows_out) in sorted(day_pool.items()):
        M = len(rows_in)
        if M == 0:
            continue
        day_res, day_st = day_batch(rows_in, rows_out, N, limit_pct, strict, fill_source, amount_mode)
        items.extend(day_res)
        day_st['sd'] = sd
        stats.append(day_st)
    return items, stats

def topk_keep(mode, k):
    if k is None:
        return None
    return keep_topk(mode, k, full_sort_key)

def reco_F():
    F = empty_filters()
    F['a45NovMidLateSpecial'] = True
    F['excludeSpecialBear'] = True
    return F

# ---- 基准: 次日开盘直接买(top-K全部, 每日池等分) / 收盘买 ----
def run_nextday_open(mode='G', keep=None, F=None, amount_mode='daily_pool'):
    day_pool = build_day_pool(mode, keep, F)
    items = []
    for sd, (rows_in, _out) in sorted(day_pool.items()):
        M = len(rows_in)
        if M == 0:
            continue
        if amount_mode == 'daily_pool':
            amt = 10000.0 / M
        else:
            amt = 10000.0
        for t in rows_in:
            r = fill_trade(t, amt, 0.0, False, mode=mode)  # limit=0 → 开盘成交(兜底)
            if r is not None:
                items.append(r[:6])
    return items, None

def run_close(mode='G', keep=None, F=None, amount_mode='daily_pool'):
    """收盘买基线: profit 直接用记录值. amount_mode: daily_pool=10000/M 等分 / fixed_1w=每单10000"""
    day_pool = build_day_pool(mode, keep, F)
    items = []
    for sd, (rows_in, _out) in sorted(day_pool.items()):
        M = len(rows_in)
        if M == 0:
            continue
        if amount_mode == 'daily_pool':
            amt = 10000.0 / M
        else:
            amt = 10000.0
        for t in rows_in:
            bp = t[fIdx['profit']] or 0
            rp = t[fIdx['return_pct']] or 0
            profit = bp * (amt / BUY_AMOUNT)
            items.append((profit, rp, str(t[fIdx['buy_date']] or ''),
                          str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items, None

def summarize(items, stats=None):
    s = compute_scaled(items)
    out = dict(s)
    if stats:
        out['budget_total'] = sum(x['total_budget'] for x in stats)
        out['budget_used'] = sum(x['used'] for x in stats)
        out['fill_rate'] = out['budget_used'] / out['budget_total'] * 100 if out['budget_total'] else 0
        out['n_touched'] = sum(x['n_touched'] for x in stats)
        out['n_buy'] = sum(x['n_buy'] for x in stats)
        out['touch_rate'] = out['n_touched'] / out['n_buy'] * 100 if out['n_buy'] else 0
        out['n_sig_total'] = sum(x['n_sig'] for x in stats)
        out['avg_disc'] = sum(x['disc_sum'] for x in stats) / sum(x['disc_amt'] for x in stats) if sum(x['disc_amt'] for x in stats) else 1.0
        out['any_touch_rate'] = sum(x['any_touch'] for x in stats) / len(stats) * 100 if stats else 0
    return out

if __name__ == '__main__':
    print('=== 自验: 复现基线(每日池, G, 剔除伪跳空) ===')
    for k, lbl in [(None,'买全部'), (1,'K=1'), (2,'K=2')]:
        keep = topk_keep('G', k)
        items, _ = run_close('G', keep=keep, F=None)
        s = summarize(items)
        print(f'  收盘 {lbl}: n={s["n"]} 净={s["net"]:+.0f} 收益率={s["ret"]:.2f}% 峰值={s["peak_capital"]:.0f}')
        items, _ = run_nextday_open('G', keep=keep, F=None)
        s = summarize(items)
        print(f'  次日开盘 {lbl}: n={s["n"]} 净={s["net"]:+.0f} 收益率={s["ret"]:.2f}% 峰值={s["peak_capital"]:.0f}')
    print('=== 自验: N=K 兜底 == 底子报告 hedge(挂-1%保证成交) ===')
    for k in [1,2]:
        keep = topk_keep('G', k)
        items, _ = run_batch('G', keep=keep, F=None, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
        s = summarize(items)
        print(f'  K={k} N={k} 兜底-1%: n={s["n"]} 净={s["net"]:+.0f} 收益率={s["ret"]:.2f}% 峰值={s["peak_capital"]:.0f} 触达率={s.get("touch_rate",0):.1f}%')

def run_batch_full(mode='G', keep=None, F=None, N=2, limit_pct=0.01, amount_mode='daily_pool'):
    """完整玩法: 依次试 -1% 限价(初始N + 降级全部推荐), 触达的买; 全部试完缺额按开盘价兜底, 预算100%用满。
    返回 (items, stats)"""
    day_pool = build_day_pool(mode, keep, F)
    items = []
    stats = []
    for sd, (rows_in, rows_out) in sorted(day_pool.items()):
        M = len(rows_in)
        if M == 0:
            continue
        init_n = min(N, M)
        per_slot = 10000.0 / init_n if init_n else 0.0
        candidates = rows_in[:init_n] + rows_out  # 初始N + 降级全部, 均按 full_sort_key 排序
        results = []
        used_amt = 0.0
        n_touched = 0
        n_buy = 0
        disc_sum = 0.0; disc_amt = 0.0
        any_touch = False
        tried = 0
        # 第一轮: 依次试 -1% 限价
        for t in candidates:
            if used_amt >= 10000 - 0.01:
                break
            amt = min(per_slot, 10000 - used_amt)
            r = fill_trade(t, amt, limit_pct, True, mode=mode)  # strict=True: 只触达买
            if r is not None:
                results.append(r[:6]); used_amt += r[5]; n_buy += 1
                if r[6]:
                    n_touched += 1; any_touch = True
                disc_sum += r[7]*r[5]; disc_amt += r[5]
            tried += 1
        # 第二轮: 缺额按开盘价兜底(所有候选品种再试一遍)
        if used_amt < 10000 - 0.01:
            for t in candidates:
                if used_amt >= 10000 - 0.01:
                    break
                amt = min(per_slot, 10000 - used_amt)
                r = fill_trade(t, amt, 0.0, False, mode=mode)  # 开盘价兜底
                if r is not None:
                    results.append(r[:6]); used_amt += r[5]; n_buy += 1
                    disc_sum += r[7]*r[5]; disc_amt += r[5]
        items.extend(results)
        stats.append(dict(total_budget=10000, used=used_amt, n_buy=n_buy, n_touched=n_touched,
                          n_sig=M, n_out=len(rows_out), disc_sum=disc_sum, disc_amt=disc_amt,
                          any_touch=any_touch, sd=sd))
    return items, stats

def run_batch_user(mode='G', keep=None, F=None, N=2, limit_pct=0.01, fill_source='outside', amount_mode='daily_pool'):
    """用户原话版: 初始N单挂top-N(每单10000/N, 触达-1%成交, 未触达留缺额);
    缺额从补单来源(池内剩余/降级)依次补挂-1%(每单10000/N, 触达成交, 未触达继续留缺额);
    最后剩余缺额按开盘价兜底买, 预算100%用满。"""
    day_pool = build_day_pool(mode, keep, F)
    items = []; stats = []
    for sd, (rows_in, rows_out) in sorted(day_pool.items()):
        M = len(rows_in)
        if M == 0:
            continue
        init_n = min(N, M)
        per_slot = 10000.0 / init_n if init_n else 0.0
        results = []; used = 0.0
        n_touched = 0; n_buy = 0
        disc_sum = 0.0; disc_amt = 0.0
        any_touch = False
        # 初始N单 (严格: 触达才买)
        for t in rows_in[:init_n]:
            r = fill_trade(t, per_slot, limit_pct, True, mode=mode)
            if r is not None:
                results.append(r[:6]); used += r[5]; n_buy += 1
                if r[6]: n_touched += 1; any_touch = True
                disc_sum += r[7]*r[5]; disc_amt += r[5]
        # 缺额 = 10000 - used; 补单从来源依次挂 -1%
        if fill_source == 'pool':
            cand = rows_in[init_n:]
        elif fill_source == 'outside':
            cand = rows_out
        else:
            cand = []
        for t in cand:
            remaining = 10000 - used
            if remaining <= 0.01:
                break
            amt = min(per_slot, remaining)
            r = fill_trade(t, amt, limit_pct, True, mode=mode)
            if r is not None:
                results.append(r[:6]); used += r[5]; n_buy += 1
                if r[6]: n_touched += 1; any_touch = True
                disc_sum += r[7]*r[5]; disc_amt += r[5]
        # 最终兜底: 剩余缺额按开盘价买(候选: top-N + 补单来源)
        if 10000 - used > 0.01:
            all_cand = rows_in[:init_n] + cand
            for t in all_cand:
                remaining = 10000 - used
                if remaining <= 0.01:
                    break
                amt = min(per_slot, remaining)
                r = fill_trade(t, amt, 0.0, False, mode=mode)
                if r is not None:
                    results.append(r[:6]); used += r[5]; n_buy += 1
                    disc_sum += r[7]*r[5]; disc_amt += r[5]
        items.extend(results)
        stats.append(dict(total_budget=10000, used=used, n_buy=n_buy, n_touched=n_touched,
                          n_sig=M, n_out=len(rows_out), disc_sum=disc_sum, disc_amt=disc_amt,
                          any_touch=any_touch, sd=sd))
    return items, stats

