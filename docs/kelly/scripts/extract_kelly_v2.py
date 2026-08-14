# ============================================================
# 用途: 组合提取(把组合名映射到具体 toggle 集, 从 v2 结果 JSON 提取各 K 档数据)
# 日期/来源: 2026-08-13 / tmp
# 结论: 组合提取工具, 供组合分析复用
# 依赖: 无
# 输入/输出: 读 /tmp/kelly_v2_results_K*.json, 输出组合提取结果
# 复现: python3 extract_kelly_v2.py
# 注意: 原文件硬编码读 /tmp/kelly_v2_results_K*.json, 如需重跑需准备该文件
# ============================================================
import json, sys

targets = {
    '3yuan(r7+exclAuxCross+g15)': 'r7MayReinforced+excludeAuxCross+greedy15',
    '5yuan(n4+n5+n6+exclAuxCross+g15)': 'n4AMay+n5MayVlow+n6MidMay+excludeAuxCross+greedy15',
    '4combo(r8+n3+v4d+g15)': 'r8PureNonMay+n3NovSpecialMon+v4d+greedy15',
    'oldBM(a45+exclM+g15)': 'a45NovMidLateSpecial+excludeMonth+greedy15',
    'Gmax(a45+exclM+v4m)': 'a45NovMidLateSpecial+excludeMonth+v4m',
    'Fmax(a45+n4+n5+n6+g15)': 'a45NovMidLateSpecial+n4AMay+n5MayVlow+n6MidMay+greedy15',
}

def norm_keys(s):
    return '+'.join(sorted(s.split('+')))

files = {
    1: {'r1-5': '/tmp/kelly_v2_results_K1_r1-5.json', 'r6': '/tmp/kelly_v2_results_K1_r6_g15.json'},
    2: {'r1-5': '/tmp/kelly_v2_results_K2_r1-5.json', 'r6': '/tmp/kelly_v2_results_K2_r6_g15.json'},
    3: {'r1-5': '/tmp/kelly_v2_results_K3_r1-5.json', 'r6': '/tmp/kelly_v2_results_K3_r6_g15.json'},
    4: {'r1-5': '/tmp/kelly_v2_results_K4_r1-5.json', 'r6': '/tmp/kelly_v2_results_K4_r6_g15.json'},
}

which_file = {
    '3yuan(r7+exclAuxCross+g15)': 'r6',
    '5yuan(n4+n5+n6+exclAuxCross+g15)': 'r1-5',
    '4combo(r8+n3+v4d+g15)': 'r1-5',
    'oldBM(a45+exclM+g15)': 'r1-5',
    'Gmax(a45+exclM+v4m)': 'r1-5',
    'Fmax(a45+n4+n5+n6+g15)': 'r1-5',
}

for K in [1, 2, 3, 4]:
    for name, tkey in targets.items():
        fp = files[K][which_file[name]]
        d = json.load(open(fp))
        tn = norm_keys(tkey)
        found = None
        for c in d:
            if norm_keys(c['keys']) == tn:
                found = c
                break
        print('=== K{} {} ==='.format(K, name))
        if found:
            print(json.dumps(found, ensure_ascii=False))
        else:
            print('NOT FOUND in ' + fp)
