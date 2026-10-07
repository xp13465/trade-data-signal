# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_204_etfscore_loud.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = 进程式 `main()` + 模块级 `PASS`/`FAIL` 计数 + `sys.exit(0/1)`(共 21 条断言)。
原脚本自身已含 §18 L48/L50 三重防线(notify 桩 + 真实 send 陷阱 + STATIC_DIR/ROOT 重定向临时树),
本包装在其外再套一层 ZeroOutboundTrap(urllib/smtplib 出口), 双保险。

断 3 条: ①rc==0 ②FAIL==0 且 PASS>=21(防 0 断言/断言被删的假绿, §18 L49)③零真实外发。
"""
from _wrap_util import run_script_main

_MIN_PASS = 21          # 实测 `断言 21 PASS / 0 FAIL`(2026-10-07 dev venv 实跑)


def test_204_etfscore_loud_wrapped():
    r = run_script_main("test_204_etfscore_loud")
    assert r.rc == 0, f"test_204 原脚本非零退出 rc={r.rc}\n{r.out[-3000:]}"
    assert r.mod.FAIL == 0, f"test_204 有 FAIL 断言: PASS={r.mod.PASS} FAIL={r.mod.FAIL}\n{r.out[-3000:]}"
    assert r.mod.PASS >= _MIN_PASS, f"test_204 仅 {r.mod.PASS} 条 PASS(下限 {_MIN_PASS}), 疑似断言被删(§18 L49)"
    assert "ALL_PASS" in r.out, "test_204 未出现 ALL_PASS 标记"
    assert r.trap_hits == [], f"零外发被破坏(§18 L48) hits={r.trap_hits}"
    print(f"test_204_etfscore_loud: {r.mod.PASS} 断言全绿, 零真实外发")