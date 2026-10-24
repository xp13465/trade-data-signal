# -*- coding: utf-8 -*-
"""#213 批2 薄包装: scripts/test_188_s06_sync_blindspot.py → CI 闸门 ⑧(单一实现)。

原脚本形态 = 进程式 `main()` + 模块级 `_fails` 清单 + `sys.exit(0/1)`。
本批对原脚本做了 4 处修改(全部见原文件内 #213 注释):
  ① `["sh", ...]` → `["bash", ...]`(CI 的 sh=dash 会让 `${BASH_SOURCE[0]}` 失效 → source 失败 exit 2);
  ② 模块级 `test_*`(会被 pytest 当用例收集 → 缺参报错)改名 `run_*`, 原 `__main__` 块抽为 `main()`;
  ③ 会话污染收尾还原(REPO/MATCH env、sys.modules["notify"]、upload_r2/ci/subprocess 被 patch 的属性、sys.path);
  ④ [C] 段 exec 业务脚本 s06_snapshot.sh 加「正面白名单」三重护栏(§18 L50 精神)。
本包装 = 调 `main()` + 接住 SystemExit + 断 rc==0 + `_fails` 空 + PASS 条数下限 + 零真实外发。

2026-10-25 隔离加固(只动包装层, 不碰生产逻辑; 病灶见 docs/ops 同批报告)
  原脚本的 `run_verify_r2` 依赖两个**隐性环境假设**, 任一条变了就红, 但都跟被测逻辑无关:
    (a) 「今天不是周日」—— upload_r2.cmd_verify_r2 在 weekday()==6 时切「周日全量对账」
        (upload_r2.py:3964-3965, 全池 500+ 文件逐个 HEAD), 而原用例的假 s3_head 只认自己
        的临时 REPO ⇒ 到周日必然大面积「不一致」(2026-10-25 周日实测 572/569)。(=L51 时间炸弹族)
    (b) 「主仓 static-site/data 里没有真实产物」—— 三个通道解析器在临时树无对应目录时
        **回退到代码树 ROOT/static-site**(upload_r2.py:3790-3808, 设计上是生产回退),
        于是把主仓 lab 65 个 + trade_sim 504 个真实文件拖进对账池。(=「依赖主仓真实数据」族)
  修法(包装层三件, 均不碰 upload_r2.py):
    ① 冻结 `u.datetime` 到非周日(照抄下面 F 段用例的 _FakeDate 写法);
    ② 把三个 ROOT 回退解析器钉到临时 STATIC_DIR(`td/static-site/data/...`);
    ③ 结构护栏: 每次 `cmd_verify_r2` 前遍历 `u._R2_CHANNELS`, 任何**存在且不在临时树内**的
       通道目录 → 直接 AssertionError 响亮失败(以后新增带 ROOT 回退的通道不再等某个周日才炸)。
  落地方式: 原脚本 run_ledger() 会 `sys.modules.pop("upload_r2")` 再重新 import
  (test_188 原文件 L104-108), 所以在用例外 patch 模块对象会被丢掉 ⇒ 用 `builtins.__import__`
  钩子在**每次** upload_r2 导入完成后套用上面的隔离(sentinel 保证幂等), 收尾完整还原。
"""
from __future__ import annotations

import builtins
import datetime as _dt
import os

from _wrap_util import run_script_main

_MIN_PASS = 34          # 原脚本 _ok() 总条数实测(= 输出里 "  PASS  " 计数), 防断言被删静默假绿(§18 L49)


# ─────────────────── 隔离三件(日期冻结 / 目录钉临时树 / 通道护栏) ───────────────────
class _FakeDate(_dt.date):
    """冻结 upload_r2 的「今天」= 2026-10-05 周一(非周日)。

    写法照抄原脚本 F 段(scripts/test_188_s06_sync_blindspot.py:252-263):
    只覆盖 date.today(), 其余委托真 datetime, 避免替换标准库类造成假失败(L51 教训)。
    """

    @classmethod
    def today(cls):
        return cls(2026, 10, 5)


class _FakeDT:
    date = _FakeDate
    datetime = _dt.datetime
    timedelta = _dt.timedelta
    timezone = _dt.timezone


def _assert_channels_confined(u):
    """结构护栏: 所有存在的通道本地目录必须落在临时 STATIC_DIR(= 临时 REPO 的 td)之内。

    目的: 以后新增任何带 `ROOT/static-site` 回退的通道, 会在这里第一时间响亮失败,
    而不是等某个周日全量对账时把主仓真实产物拖进来、静默翻红(§23.2 根因修复而非补症状)。
    """
    root = os.path.realpath(str(u.STATIC_DIR))
    offenders = []
    for ch in u._R2_CHANNELS:
        label = ch.get("label")
        try:
            d = ch["local_dir"]()
        except Exception as e:                       # 解析器自己炸 = 也要响, 不静默跳过
            offenders.append((label, f"解析异常 {type(e).__name__}: {e}"))
            continue
        if not d.exists():
            continue                                 # 不存在的目录 verify-r2 本就会跳过
        rp = os.path.realpath(str(d))
        try:
            inside = os.path.commonpath([root, rp]) == root
        except ValueError:
            inside = False
        if not inside:
            offenders.append((label, str(d)))
    assert not offenders, (
        "verify-r2 通道解析到了临时树之外的真实目录(测试隔离被破坏): "
        f"{offenders}; 允许根目录 = {root}。"
        "修法: 在 _isolate_upload_r2() 里把该通道的解析器一并钉到 u.STATIC_DIR。"
    )


def _isolate_upload_r2(u):
    """upload_r2 每次(重新)导入后套用: 三个 ROOT 回退解析器 → 临时树; 冻结日期; 装通道护栏。"""
    if getattr(u, "_t188_isolated", False):          # 幂等: 同模块不重复包裹
        return

    # ① 三个通道的 ROOT/static-site 回退(upload_r2.py:3790-3808)一律钉到临时 REPO 树。
    #    dd(原脚本) = td/static-site/data; 这里用 u.STATIC_DIR(= td/static-site)在**调用时**拼,
    #    与 td 同源, 且不依赖用例外部知道 td。
    #    ⚠ 两处都要改: `_R2_CHANNELS` 在定义时**直接持有函数引用**(upload_r2.py:3821-3826),
    #    只换模块名 `_resolve_*` 不会影响已入表的 local_dir(第一版实测就栽在这, 被护栏当场抓住)。
    _dir_overrides = {
        "lab": lambda: u.STATIC_DIR / "data" / "lab",
        "trade-sim": lambda: u.STATIC_DIR,
        "trade-sim-json": lambda: u.STATIC_DIR / "data" / "trade_sim",
    }
    u._resolve_lab_dir = _dir_overrides["lab"]
    u._resolve_trade_sim_json_dir = _dir_overrides["trade-sim-json"]
    u._resolve_trade_sim_html_dir = _dir_overrides["trade-sim"]
    u._R2_CHANNELS = [
        dict(ch, local_dir=_dir_overrides[ch["label"]]) if ch.get("label") in _dir_overrides else ch
        for ch in u._R2_CHANNELS
    ]

    # ② 冻结「今天」→ 稳定走平日增量分支(不再依赖今天是星期几)
    u.datetime = _FakeDT

    # ③ 结构护栏: 每次对账前先验通道目录都在临时树内(见 _assert_channels_confined)
    _orig_verify = u.cmd_verify_r2

    def _guarded_verify():
        _assert_channels_confined(u)
        return _orig_verify()

    u.cmd_verify_r2 = _guarded_verify
    u._t188_isolated = True


def _run_with_upload_r2_isolation():
    """在 builtins.__import__ 上挂钩子跑原脚本, 收尾还原(防污染同 pytest 会话其他用例)。"""
    real_import = builtins.__import__

    def _hooked_import(name, globals=None, locals=None, fromlist=(), level=0):
        mod = real_import(name, globals, locals, fromlist, level)
        if level == 0 and name == "upload_r2":
            _isolate_upload_r2(mod)
        return mod

    builtins.__import__ = _hooked_import
    try:
        return run_script_main("test_188_s06_sync_blindspot")
    finally:
        builtins.__import__ = real_import


def test_188_s06_sync_blindspot_wrapped():
    r = _run_with_upload_r2_isolation()
    assert r.rc == 0, f"test_188 原脚本非零退出 rc={r.rc}\n{r.out[-3000:]}"
    assert r.mod._fails == [], f"test_188 有 FAIL 断言: {r.mod._fails}\n{r.out[-3000:]}"
    n_pass = r.out.count("  PASS  ")
    assert n_pass >= _MIN_PASS, f"test_188 仅 {n_pass} 条 PASS(下限 {_MIN_PASS}), 疑似断言被删(§18 L49)"
    assert "ALL_PASS" in r.out, "test_188 未出现 ALL_PASS 标记"
    # 反证隔离生效: 平日分支下不应出现「大面积不一致(阈值 50)」信号
    # (2026-10-25 周日实测原用例 572/569 个; 日期冻结 + 目录钉临时树后必须为 0)
    assert "不一致 key(阈值 50)" not in r.out, "verify-r2 仍跑到周日全量分支/拖入主仓真实数据"
    assert r.trap_hits == [], f"零外发被破坏(§18 L48) hits={r.trap_hits}"
    print(f"test_188_s06_sync_blindspot: {n_pass} 断言全绿, 零真实外发")