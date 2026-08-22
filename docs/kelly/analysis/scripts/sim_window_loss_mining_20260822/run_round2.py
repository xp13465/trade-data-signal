# -*- coding: utf-8 -*-
"""二轮挖掘 一键汇总(2026-08-22)。
顺序执行 mine10-17 全链路,产出 data/mine10-17 全部 json。
复现:python3 run_round2.py(约 3-5 分钟,mine14 最慢)
"""
import subprocess, sys, os, time
BASE = os.path.dirname(os.path.abspath(__file__))
STEPS = ['mine10_features.py', 'mine11_univariate.py', 'mine12_equity.py', 'mine13_calendar.py',
         'mine14_subgroup.py', 'mine15_overlay.py', 'mine16_candidates.py', 'mine17_modes.py']
for s in STEPS:
    t0 = time.time()
    print(f'=== {s} ===', flush=True)
    r = subprocess.run([sys.executable, os.path.join(BASE, s)], cwd=BASE)
    if r.returncode != 0:
        print(f'FAILED {s}'); sys.exit(1)
    print(f'--- {s} done in {time.time()-t0:.0f}s')
print('ALL DONE')
