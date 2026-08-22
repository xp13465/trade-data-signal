# -*- coding: utf-8 -*-
"""三轮挖掘 ①替补盲区地图(2026-08-22)。

目的:   回答「哪些替补为什么没有被过滤到?差什么条件?」——对补位口径下顶上来的 45 笔替补,
        逐一标注 9 键(8键默认开+bullAuxBackupStop)为何都不命中(差哪个条件),并反向统计
        139 笔被拦笔各键实际贡献,形成「9 键射程表」。
口径:   补位口径(memory filter-backtest-position-fill-caliber);9 键链路与 r3_common 自检锚点一致。
输入:   static-site/data/signal_kelly_trades.json(经 r3_common.prepare_rows)
输出:   stdout 盲区地图全套表格 + data/mine12_blindmap.json
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/mine12_substitute_blindmap.py
"""
import os, sys, json, math, datetime
from collections import Counter, defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r3_common as C
from sim_core import buyprice_bin, buy_weekday

st = C.get_sets()
rows, fIdx = C.ensure()
i = fIdx

def ctx(t):
    """提取判定上下文: 与 sim_core.passes_fade 同源的字段口径。"""
    bd = str(t[i['buy_date']] or '')
    mm = bd[4:6] if len(bd) >= 6 else ''
    dd = int(bd[6:8]) if len(bd) >= 8 else 0
    return dict(sig=t[i['signal']] or '', mm=mm, dd=dd, wd=buy_weekday(bd),
                bpb=buyprice_bin(t[i['buy_price']]),
                ts=float(t[i['track_score']]) if t[i['track_score']] not in (None, '') else 999.0,
                tier=t[i['market_tier']] or '',
                mktD=t[len(fIdx)] or '', etfD=t[len(fIdx)+1] or '', ratD=t[len(fIdx)+2] or '',
                rating=str(t[i['rating']] or ''), sd=str(t[i['signal_date']] or ''),
                q=math.ceil(int(mm)/3) if mm else 0)

# ---- 9 键定义(子规则级, 每条返回 bool; 与 sim_core.passes_fade 逐字同源) ----
def subrules(c):
    """返回 [(key_id, rule_name, hit_bool)], hit=True 表示该子规则会拦掉此笔。"""
    out = []
    sig, mm, dd, wd, bpb, ts = c['sig'], c['mm'], c['dd'], c['wd'], c['bpb'], c['ts']
    tier, mktD, ratD, q = c['tier'], c['mktD'], c['ratD'], c['q']
    # 键1 excludeAuxCross (活跃月3,5)
    out.append(('K1', 'aux×3/5月', sig == 'buy_aux' and mm in ('03', '05')))
    # 键2 excludeSpecialBear (全月)
    out.append(('K2', 'special×熊市主跌|下降期', sig == 'buy_special' and tier in ('熊市·主跌', '下降期')))
    # 键3 n2NovSpecialIndustry (活跃月3,5,11)
    out.append(('K3', 'special×11月×industry', sig == 'buy_special' and mm == '11' and mktD == 'industry'))
    # 键4 r7MayReinforced (活跃月3,5,11)
    out.append(('K4a', 'r7:a域×5月', mktD == 'a' and mm == '05'))
    out.append(('K4b', 'r7:mid评分×5月', ratD == 'mid' and mm == '05'))
    out.append(('K4c', 'r7:5月×vlow价', mm == '05' and bpb == 'vlow'))
    out.append(('K4d', 'r7:3月周二×高价', mm == '03' and wd == 2 and bpb == 'high'))
    out.append(('K4e', 'r7:special×11月industry', sig == 'buy_special' and mm == '11' and mktD == 'industry'))
    out.append(('K4f', 'r7:special×11月周一', sig == 'buy_special' and mm == '11' and wd == 0))
    # 键5 greedy15 (全月)
    out.append(('G1', 'g15:special×5月', sig == 'buy_special' and mm == '05'))
    out.append(('G2', 'g15:special×11月×concept', sig == 'buy_special' and mm == '11' and mktD == 'concept'))
    out.append(('G3', 'g15:special×3月', sig == 'buy_special' and mm == '03'))
    out.append(('G4', 'g15:aux×1月', sig == 'buy_aux' and mm == '01'))
    out.append(('G5', 'g15:Q2×vlow×aux×concept', q == 2 and bpb == 'vlow' and sig == 'buy_aux' and mktD == 'concept'))
    out.append(('G6', 'g15:buy×1月', sig == 'buy' and mm == '01'))
    out.append(('G7', 'g15:3月周二×concept×low', mm == '03' and wd == 2 and mktD == 'concept' and ratD == 'low'))
    out.append(('G8', 'g15:aux×12月×ts<50', sig == 'buy_aux' and mm == '12' and ts < 50))
    out.append(('G9', 'g15:6月×vlow×low', mm == '06' and bpb == 'vlow' and ratD == 'low'))
    out.append(('G10', 'g15:aux×5月', sig == 'buy_aux' and mm == '05'))
    out.append(('G11', 'g15:special×11月×industry', sig == 'buy_special' and mm == '11' and mktD == 'industry'))
    out.append(('G12', 'g15:4月周三×concept×ts<50', mm == '04' and wd == 2 and mktD == 'concept' and ts < 50))
    out.append(('G13', 'g15:global×Q1×aux×low', mktD == 'global' and q == 1 and sig == 'buy_aux' and ratD == 'low'))
    out.append(('G14', 'g15:1月×低价×special×concept', mm == '01' and bpb == 'low' and sig == 'buy_special' and mktD == 'concept'))
    out.append(('G15', 'g15:special×9月×周二', sig == 'buy_special' and mm == '09' and wd == 2))
    # 键6 janMidRating (活跃月1)
    out.append(('K6', '1月中旬×mid评分', mm == '01' and 11 <= dd <= 20 and ratD == 'mid'))
    # 键7 janMidSpecial (活跃月1)
    out.append(('K7', 'special×1月中旬', sig == 'buy_special' and mm == '01' and 11 <= dd <= 20))
    # 键8 k2c5HkChase (全月)
    out.append(('K8', 'special|backup×hk域', sig in ('buy_special', 'buy_backup') and mktD == 'hk'))
    # 键9 bullAuxBackupStop(一轮候选1, 全月)
    out.append(('K9', '牛主升×aux|backup', tier == '牛市·主升' and sig in ('buy_aux', 'buy_backup')))
    return out

KEY_GROUP = {'K1': '键1 aux跨月', 'K2': '键2 special熊跌', 'K3': '键3 11月行业', 'K4a': '键4 五月强化', 'K4b': '键4 五月强化',
             'K4c': '键4 五月强化', 'K4d': '键4 五月强化', 'K4e': '键4 五月强化', 'K4f': '键4 五月强化',
             'G1': '键5 greedy15', 'G2': '键5 greedy15', 'G3': '键5 greedy15', 'G4': '键5 greedy15', 'G5': '键5 greedy15',
             'G6': '键5 greedy15', 'G7': '键5 greedy15', 'G8': '键5 greedy15', 'G9': '键5 greedy15', 'G10': '键5 greedy15',
             'G11': '键5 greedy15', 'G12': '键5 greedy15', 'G13': '键5 greedy15', 'G14': '键5 greedy15', 'G15': '键5 greedy15',
             'K6': '键6 1月中评', 'K7': '键7 1月中sp', 'K8': '键8 港股追涨', 'K9': '键9 牛主升辅备'}

print('=' * 96)
print('①a 139 笔被拦笔:各键实际拦截贡献(对照:键都在干什么)')
print('=' * 96)
block_by_key = Counter()
for t in st['blocked']:
    hits = [kid for kid, nm, hit in subrules(ctx(t)) if hit]
    if not hits:
        block_by_key['(无键命中?)'] += 1
    else:
        block_by_key[KEY_GROUP[hits[0]]] += 1
for k, n in block_by_key.most_common():
    print(f'  {k}: {n} 笔')

print()
print('=' * 96)
print('①b 45 笔替补:逐笔「最近键」归因(命中任意子规则=会被拦;全部未命中=从缝里掉进来)')
print('=' * 96)

def nearest_miss(c):
    """找差条件最少的子规则, 返回 (miss_n, key_desc)。miss_n=距被拦还差几个条件。"""
    best = None
    for kid, nm, hit in subrules(c):
        if hit:
            return 0, f'{KEY_GROUP[kid]}·{nm}'
    # 未命中: 对每个子规则计算 miss 条件数
    def miss_of(kid):
        sig, mm, dd, wd, bpb, ts = c['sig'], c['mm'], c['dd'], c['wd'], c['bpb'], c['ts']
        tier, mktD, ratD, q, rating = c['tier'], c['mktD'], c['ratD'], c['q'], c['rating']
        conds = {
            'K1': [('sig', sig == 'buy_aux'), ('月∈{3,5}', mm in ('03', '05'))],
            'K2': [('sig=special', sig == 'buy_special'), ('档位∈{熊主跌,下降期}', tier in ('熊市·主跌', '下降期'))],
            'K3': [('sig=special', sig == 'buy_special'), ('月=11', mm == '11'), ('industry域', mktD == 'industry')],
            'K4b': [('mid评分', ratD == 'mid'), ('月=5', mm == '05')],
            'K4c': [('月=5', mm == '05'), ('vlow价', bpb == 'vlow')],
            'K4d': [('月=3', mm == '03'), ('周二', wd == 2), ('high价', bpb == 'high')],
            'K4e': [('sig=special', sig == 'buy_special'), ('月=11', mm == '11'), ('industry域', mktD == 'industry')],
            'K4f': [('sig=special', sig == 'buy_special'), ('月=11', mm == '11'), ('周一', wd == 0)],
            'G1': [('sig=special', sig == 'buy_special'), ('月=5', mm == '05')],
            'G2': [('sig=special', sig == 'buy_special'), ('月=11', mm == '11'), ('concept域', mktD == 'concept')],
            'G3': [('sig=special', sig == 'buy_special'), ('月=3', mm == '03')],
            'G4': [('sig=aux', sig == 'buy_aux'), ('月=1', mm == '01')],
            'G6': [('sig=buy', sig == 'buy'), ('月=1', mm == '01')],
            'G7': [('月=3', mm == '03'), ('周二', wd == 2), ('concept域', mktD == 'concept'), ('low评', ratD == 'low')],
            'G8': [('sig=aux', sig == 'buy_aux'), ('月=12', mm == '12'), ('ts<50', ts < 50)],
            'G9': [('月=6', mm == '06'), ('vlow价', bpb == 'vlow'), ('low评', ratD == 'low')],
            'G10': [('sig=aux', sig == 'buy_aux'), ('月=5', mm == '05')],
            'G11': [('sig=special', sig == 'buy_special'), ('月=11', mm == '11'), ('industry域', mktD == 'industry')],
            'G12': [('月=4', mm == '04'), ('周三', wd == 2), ('concept域', mktD == 'concept'), ('ts<50', ts < 50)],
            'G13': [('global域', mktD == 'global'), ('Q1', q == 1), ('sig=aux', sig == 'buy_aux'), ('low评', ratD == 'low')],
            'G14': [('月=1', mm == '01'), ('low价', bpb == 'low'), ('sig=special', sig == 'buy_special'), ('concept域', mktD == 'concept')],
            'G15': [('sig=special', sig == 'buy_special'), ('月=9', mm == '09'), ('周二', wd == 2)],
            'K6': [('月=1', mm == '01'), ('11-20日', 11 <= dd <= 20), ('mid评', ratD == 'mid')],
            'K7': [('sig=special', sig == 'buy_special'), ('月=1', mm == '01'), ('11-20日', 11 <= dd <= 20)],
            'K8': [('sig∈{sp,bk}', sig in ('buy_special', 'buy_backup')), ('hk域', mktD == 'hk')],
            'K9': [('档位=牛主升', tier == '牛市·主升'), ('sig∈{aux,bk}', sig in ('buy_aux', 'buy_backup'))],
        }[kid]
        return sum(1 for _, ok in conds if not ok), ';'.join(nm for nm, ok in conds if not ok)
    kids = ['K1','K2','K3','K4b','K4c','K4d','K4e','K4f','G1','G2','G3','G4','G6','G7','G8','G9','G10','G11','G12','G13','G14','G15','K6','K7','K8','K9']
    scored = sorted(((miss_of(k)[0], KEY_GROUP[k] + '·缺[' + miss_of(k)[1] + ']', k) for k in kids))
    return scored[0][0], scored[0][1]

rows_out = []
grp_stat = defaultdict(lambda: dict(n=0, pnl=0.0))
for t in sorted(st['filled'], key=lambda x: str(x[i['signal_date']])):
    c = ctx(t)
    p = C.pnl_of(t)
    mn, desc = nearest_miss(c)
    dom = 'A股' if c['mktD'] == 'a' or (c['mktD'] == '' and c['tier']) else (c['mktD'] or '无域标')
    grp = f"{c['sig']}×{'A股' if dom=='A股' else dom}"
    grp_stat[grp]['n'] += 1; grp_stat[grp]['pnl'] += p
    print(f"{c['sd']} {c['sig']:<12} {str(t[i['index_id']]):<13} rat={c['rating']:<4} ts={c['ts']:>5.1f} 月={c['mm']} 域={dom:<7} pnl={p:+7.0f} | 最近键:{desc}")
    rows_out.append(dict(sd=c['sd'], sig=c['sig'], index_id=t[i['index_id']], rating=c['rating'],
                         ts=c['ts'], month=c['mm'], dom=dom, pnl=p, nearest_miss=desc, miss_n=mn))

print()
print('①c 替补按「sig×域」分组净额:')
tot_n = tot_p = 0
for g, v in sorted(grp_stat.items(), key=lambda kv: kv[1]['pnl']):
    print(f"  {g:<22} {v['n']:>3}笔 {v['pnl']:+9.0f}元")
    tot_n += v['n']; tot_p += v['pnl']
print(f"  {'合计':<22} {tot_n:>3}笔 {tot_p:+9.0f}元")

# 缺条件类型聚合
print()
print('①d 「差什么条件」聚合(最近键的缺失条件词频):')
wordcnt = Counter()
for r in rows_out:
    for seg in r['nearest_miss'].split('缺[')[-1].rstrip(']').split(';'):
        wordcnt[seg] += 1
for w, n in wordcnt.most_common(12):
    print(f'  {w}: {n} 笔')

out = dict(generated_at=datetime.datetime.now().isoformat(),
           block_by_key=dict(block_by_key),
           filled_rows=rows_out,
           group_stat={g: dict(v) for g, v in grp_stat.items()})
with open(os.path.join(HERE, 'data/mine12_blindmap.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=float)
print('\ndata/mine12_blindmap.json written')
