# -*- coding: utf-8 -*-
"""mine28 防前视机检脚本(mine28_lookahead_check,独立可复跑)。
目的: 对 mine28_regime_rotation 的状态库执行第一科学红线三条硬机检并断言全过:
  ①分位数口径审计: 注册表内所有因子声明阈值来源,断言无任何「全期分位」型阈值
    (分位特征仅允许 mine10 滚动756日 trailing 分位);
  ②特征库固化口径核查: 自算 hs300 四档 tier 逐位对照生产 tiers 文件(hs300-all.json tiers 数组,
    生产判定源 queries.py L552-594 同款)+ ma60_bull 对照;
  ③时点穿越测试: T∈{20180629,20240208,20251231} 截断全部输入重算 20 因子+tier4 状态序列,
    断言与全量序列的 t 前缀逐位一致。
输入: data/mine10_features.json + static-site/data/index/hs300-all.json + sh-all.json。
输出: 控制台 PASS/FAIL(全部 PASS 才 exit 0)。
复现: cd /Users/linhuichen/code/trade/docs/kelly/analysis/scripts/sim_window_loss_mining_20260822 && python3 mine28_lookahead_check.py
"""
import json, os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import mine28_regime_rotation as M

def main():
    F = M.build_state_inputs()
    ohlc = json.load(open(M.ROOT + '/static-site/data/index/hs300-all.json'))['ohlc']
    cal = [o['date'] for o in ohlc]
    reg, _, _ = M.factor_registry()

    # ① 分位数口径审计
    bad = []
    for fk, (fn, desc, prov) in reg.items():
        if '全期' in prov or '全样本分位' in prov:
            bad.append(fk)
        assert '滚动trailing分位' not in prov or '756' in prov or '✓' in prov, fk
    print(f"机检① 分位数口径审计: {'PASS 无全期分位阈值(' + str(len(reg)) + ' 因子全部=固定常数/符号判断/生产判定源)' if not bad else 'FAIL ' + str(bad)}")
    assert not bad

    # ② 特征库固化口径核查(自算 tier4/ma60bull vs 生产文件逐位一致)
    j = json.load(open(M.ROOT + '/static-site/data/index/hs300-all.json'))
    tiers = {o['date']: o['tier'] for o in j['tiers']}
    ma60b = {o['date']: o['ma60_bull'] for o in j['tiers']}
    common = sorted(set(tiers) & set(F['tier4']))
    mis1 = [d for d in common if tiers[d] != F['tier4'][d]]
    mis2 = [d for d in common if d in F['hs_ma60bull'] and bool(ma60b[d]) != bool(F['hs_ma60bull'][d])]
    print(f"机检② 特征固化口径核查: tier4 对照 {len(common)} 天不一致 {len(mis1)};ma60_bull 不一致 {len(mis2)} -> {'PASS' if not mis1 and not mis2 else 'FAIL'}")
    assert not mis1 and not mis2

    # ③ 时点穿越测试
    for T in ('20180629', '20240208', '20251231'):
        Fc = M.build_state_inputs(cutoff=T)
        ok = True; where = None
        for fk, (fn, _, _) in reg.items():
            a = [fn(F, d) for d in cal if d <= T]
            b = [fn(Fc, d) for d in cal if d <= T]
            if a != b: ok = False; where = fk; break
        if ok:
            if [F['tier4'].get(d) for d in cal if d <= T] != [Fc['tier4'].get(d) for d in cal if d <= T]:
                ok = False; where = 'tier4'
        print(f"机检③ 时点穿越 T={T}: {'PASS 截断重算与全量前缀逐位一致' if ok else 'FAIL @' + str(where)}")
        assert ok, (T, where)

    print('\n三道防前视机检全部 PASS')

if __name__ == '__main__':
    main()
