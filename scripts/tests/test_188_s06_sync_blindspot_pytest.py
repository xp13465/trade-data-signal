# -*- coding: utf-8 -*-
"""#213 批2 薄包装: scripts/test_188_s06_sync_blindspot.py → CI 闸门 ⑧(单一实现)。

原脚本形态 = 进程式 `main()` + 模块级 `_fails` 清单 + `sys.exit(0/1)`。
本批对原脚本做了 4 处修改(全部见原文件内 #213 注释):
  ① `["sh", ...]` → `["bash", ...]`(CI 的 sh=dash 会让 `${BASH_SOURCE[0]}` 失效 → source 失败 exit 2);
  ② 模块级 `test_*`(会被 pytest 当用例收集 → 缺参报错)改名 `run_*`, 原 `__main__` 块抽为 `main()`;
  ③ 会话污染收尾还原(REPO/MATCH env、sys.modules["notify"]、upload_r2/ci/subprocess 被 patch 的属性、sys.path);
  ④ [C] 段 exec 业务脚本 s06_snapshot.sh 加「正面白名单」三重护栏(§18 L50 精神)。
本包装 = 调 `main()` + 接住 SystemExit + 断 rc==0 + `_fails` 空 + PASS 条数下限 + 零真实外发。
"""
from _wrap_util import run_script_main

_MIN_PASS = 34          # 原脚本 _ok() 总条数实测(= 输出里 "  PASS  " 计数), 防断言被删静默假绿(§18 L49)


def test_188_s06_sync_blindspot_wrapped():
    r = run_script_main("test_188_s06_sync_blindspot")
    assert r.rc == 0, f"test_188 原脚本非零退出 rc={r.rc}\n{r.out[-3000:]}"
    assert r.mod._fails == [], f"test_188 有 FAIL 断言: {r.mod._fails}\n{r.out[-3000:]}"
    n_pass = r.out.count("  PASS  ")
    assert n_pass >= _MIN_PASS, f"test_188 仅 {n_pass} 条 PASS(下限 {_MIN_PASS}), 疑似断言被删(§18 L49)"
    assert "ALL_PASS" in r.out, "test_188 未出现 ALL_PASS 标记"
    assert r.trap_hits == [], f"零外发被破坏(§18 L48) hits={r.trap_hits}"
    print(f"test_188_s06_sync_blindspot: {n_pass} 断言全绿, 零真实外发")