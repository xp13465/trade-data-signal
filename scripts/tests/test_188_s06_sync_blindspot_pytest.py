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

2026-10-25 隔离生效性反证(审查必修1: 旧断言只看 stdout, 而阈值告警只写 stderr ⇒ 永远通过)
  `run_script_main` 现在同时收 stderr(见 _wrap_util.run_script_main 文档), 本文件对
  out+err 一起断言, 并加**可观察计数**: 隔离钩子生效 ≥1 次 + 通道护栏执行 ≥1 次。
  为什么要两层: CI 里 `static-site/data` 不入 git(数据走 R2) ⇒ 无主仓真实产物 ⇒ 单靠
  「输出里没有 572/569」在 CI 永远不会触发, 判别力会押在「本机恰好有数据」上; 计数层则
  在「钩子没接上 / 隔离被拿掉」时任何环境都必红。

━━━ 七轴边界清单(交审查关 §10.8 独立复核对账用; 每条 = 测/不测 + 理由) ━━━
  ① 输入域(日期相位): **测** —— 周日 2026-10-25(复现原病灶, 572/569)/ `_FakeDate` 冻结的
     2026-10-05 周一 / TZ=UTC 平移(本地周日 03:xx → UTC 周六), 覆盖 ≥2 个日期相位。
  ② 状态组合(通道目录存在性): **测** —— 临时树有目录(正常对账) / 主仓真实目录存在(软链复现,
     要求 1 passed 且 572=0) / 目录不存在(护栏跳过, 见下方「显式不测」第 1 条)。
  ③ 时序: **测** —— 原脚本 run_verify_r2 调用 2 次(原文件 L397/L399), 断言护栏执行 ≥1 次;
     `_FakeDate` 只改写 `date.today()`, 不冻结进程真实时钟, 其余时间语义不受影响(预期内)。
  ④ 上下游依赖: **测** —— 3 个带 ROOT 回退的解析器 + 其余通道全部经 `_assert_channels_confined`
     复核; import 钩子在「模块被 pop 后重新 import」的真实行为下仍生效(原脚本 L104-108)。
  ⑤ 极值边界: **测** —— 550+ 大面积不一致(572/569)必须归零; **不测** —— 生产 500+ 文件规模下
     的性能/超时(本用例验证隔离性, 不是性能测试; 超时由 CI 自身窗口兜底)。
  ⑥ 回滚路径: **测** —— `builtins.__import__` try/finally 还原 + `_wrap_util` 模块快照还原,
     全量 pytest 三轮(软链 / 无软链 / TZ=UTC)均 1386 passed、2 skipped, 证明无跨用例污染。
  ⑦ 并发与重入: **不测并发** —— 本项目 CI 串行跑 pytest(未启用 xdist); 若将来启用, 各 worker
     是独立进程不共享这些全局, 但同一进程内的并行执行不存在, 故无并发面可测。**测重入** ——
     `_t188_isolated` sentinel 保证同模块重复 import 只包裹一次(run_ledger 二次 import 场景已覆盖)。

━━━ 显式「不测 + 理由」(审查差集 d 逐条声明) ━━━
  1) 新通道目录在临时树里不存在 ⇒ 护栏 `if not d.exists(): continue` 直接跳过。
     理由: 与 verify-r2 自身行为一致 —— 它同样跳过不存在的通道目录(不存在即 0 文件可对账),
     所以「跳过」不会掩盖任何真实数据泄漏; 真正的风险形态是「目录存在且落在树外」, 由 ② 的
     主仓软链场景实测覆盖(护栏当场 AssertionError)。
  2) `_FakeDT` 只实现 date/datetime/timedelta/timezone, 其余属性缺失会 AttributeError。
     理由: 只替换 upload_r2 模块内的 `datetime` 名; grep 实测 upload_r2.py 全部用法仅
     `datetime.date` / `datetime.datetime`(含其 now/strptime 类方法) / `datetime.timedelta`,
     已被委托; 将来生产若新增 `datetime.time` 等用法, 本替身会 **AttributeError 响亮失败**
     (而不是静默算错日期), 属可接受的失败模式, 届时补一行委托即可。
  3) 全局补丁 / 会话顺序交错: 还原保证 = ①`builtins.__import__` 在 try/finally 还原(被测脚本
     抛异常也还原); ②upload_r2 模块由 `_wrap_util._snapshot_modules/_restore_modules` 在每次
     `run_script_main` 前后快照/还原, 本用例对模块属性的改动不会漏给后续用例;
     ③sentinel 保证同模块重复 import 只包裹一次。实测: 与 test_193 等同样 patch upload_r2 的
     用例同会话连跑三轮全绿。
"""
from __future__ import annotations

import builtins
import datetime as _dt
import os

from _wrap_util import run_script_main

_MIN_PASS = 34          # 原脚本 _ok() 总条数实测(= 输出里 "  PASS  " 计数), 防断言被删静默假绿(§18 L49)

# 隔离生效的**可观察记录**(审查必修1): 钩子被调用 / 护栏被执行各记一行。
# 只在断言里消费, 不参与被测逻辑; 每次 `_run_with_upload_r2_isolation()` 开头清空。
_ISOLATION_EVENTS: list[str] = []


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
    _ISOLATION_EVENTS.append(f"isolate:{id(u)}")     # 可观察记录: 钩子确被调用(每次 import 都记)
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
        _ISOLATION_EVENTS.append("guard")            # 可观察记录: 隔离确被应用到对账入口
        _assert_channels_confined(u)
        return _orig_verify()

    u.cmd_verify_r2 = _guarded_verify
    u._t188_isolated = True


def _run_with_upload_r2_isolation():
    """在 builtins.__import__ 上挂钩子跑原脚本, 收尾还原(防污染同 pytest 会话其他用例)。"""
    _ISOLATION_EVENTS.clear()                        # 本次运行的记录从头算(不继承上一次)
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
    # ── 隔离生效反证(审查必修1: 原断言只看 out, 而阈值告警只写 stderr ⇒ 空断言) ──
    # 第一层「钩子/护栏真跑过」: 隔离被拿掉 / 钩子没接上 ⇒ 计数为 0 ⇒ 任何环境都必红。
    # 必须留这一层的原因: CI 的 static-site/data 不入 git(数据走 R2) ⇒ 无主仓真实产物 ⇒
    # 第二层的输出信号在 CI 永远不触发, 只留第二层 = 判别力押在「本机恰好有数据」上。
    assert sum(e.startswith("isolate:") for e in _ISOLATION_EVENTS) >= 1, (
        "upload_r2 隔离钩子一次都没生效(builtins.__import__ 钩子未接上 / 隔离被拿掉?)")
    assert _ISOLATION_EVENTS.count("guard") >= 1, (
        "通道护栏一次都没执行 ⇒ _isolate_upload_r2 未真正应用到 cmd_verify_r2 入口")
    # 第二层「隔离真达到效果」: 阈值告警是 stderr(upload_r2.py:4122-4123), 必须 out+err 一起断言。
    # 2026-10-25 周日实测原用例 572/569 个; 日期冻结 + 目录钉临时树后必须为 0。
    combined = r.out + r.err
    n_mass = combined.count("不一致 key(阈值 50)")
    assert n_mass == 0, (
        f"verify-r2 仍跑到周日全量分支/拖入主仓真实数据(阈值告警出现 {n_mass} 次)\n"
        f"stderr 摘要: {r.err[-2000:] or '(空)'}")
    assert r.trap_hits == [], f"零外发被破坏(§18 L48) hits={r.trap_hits}"
    print(f"test_188_s06_sync_blindspot: {n_pass} 断言全绿, 零真实外发")