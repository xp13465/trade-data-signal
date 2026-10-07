# -*- coding: utf-8 -*-
"""#213 批2 薄包装: scripts/test_ai_macro_hit_filters.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = 进程式 `main()` + 本地 `ok` 计数 + `sys.exit(0/1)`(共 13 项断言, 打印 `== 13/13 PASS ==`)。
依赖: 顶层 `import app.queries`(真 pandas/numpy/pyarrow) —— 这正是 #213 方案 A2 在 CI 侧
`pip install numpy/pandas/pyarrow` 的解锁对象(见 .github/workflows/ci.yml ⑧ 步注释 +
docs/ops/213-batch2-dependency-decision-20261007.md)。
本包装 = 调 `main()` + 接住 SystemExit + 断 rc==0 且输出含 `13/13`(防断言被删的假绿, §18 L49)+ 零真实外发。
"""
from _wrap_util import run_script_main

_MIN_ITEMS = 13         # 原脚本 total=13


def test_ai_macro_hit_filters_wrapped():
    r = run_script_main("test_ai_macro_hit_filters")
    assert r.rc == 0, f"test_ai_macro_hit_filters 原脚本非零退出 rc={r.rc}\n{r.out[-3000:]}"
    assert f"{_MIN_ITEMS}/{_MIN_ITEMS} PASS" in r.out, (
        f"未出现 {_MIN_ITEMS}/{_MIN_ITEMS} PASS 标记(疑似断言被删/收敛口径变了)\n{r.out[-3000:]}")
    assert r.trap_hits == [], f"零外发被破坏(§18 L48) hits={r.trap_hits}"
    print(f"test_ai_macro_hit_filters: {_MIN_ITEMS} 项断言全绿, 零真实外发")