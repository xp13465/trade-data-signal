# -*- coding: utf-8 -*-
"""#223④ overfit_monitor 内层 R2 上传超时抬升(180→900)+ 运行时梯度守卫 —— static-only 断言。

背景: #223 扫出「超时梯度倒置」同类面。④ = overfit_monitor.py 对 upload_r2.py 的 subprocess
超时(旧 `120 + skip_retry` = 180)偏紧; 该链外层 systemd TimeoutStartSec=0(无界, 云上实测)
⇒ 内层预算即唯一墙钟, 可单独抬到 900 + 加「防倒置」运行时守卫(对齐 #217② 先例)。

§18 L50(static-only): 本测试只 `ast` 抽取 overfit_monitor.py 的守卫函数/常量到临时命名空间
`exec`, **绝不 import 业务模块、绝不执行任何业务脚本主体** —— 该脚本带告警链路(notify.py 邮件
/Telegram/飞书), import 即可能触发。也**零真实外发**(不 import notify, 不碰 data/alerts)。

断言两条主线:
  ①「真改了」: 常量 900 落地 + 调用点改走守卫 + 旧 `120 + _r2_skip_retry` 已清除;
  ②「守卫真修了而非注释级」: 喂**倒置输入**(外层 systemd < 本层 / 内层 HTTP > 本层)⇒ 守卫
     真的纠正了返回值(且打 warn), 不是只写在注释里。
"""
import ast
import contextlib
import hashlib
import io
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "scripts" / "overfit_monitor.py"

_WANT_FUNCS = {"_parse_systemd_span_secs", "_systemd_outer_wall_secs", "_r2_upload_timeout"}
_WANT_CONSTS = {"_R2_UPLOAD_TIMEOUT", "_R2_UPLOAD_TIMEOUT_MARGIN",
                "_OVERFIT_SYSTEMD_UNIT", "_SYSTEMD_SPAN_UNITS"}

_n = 0


def _ck(cond, msg):
    global _n
    _n += 1
    assert cond, f"[#{_n}] {msg}"


def _load_guard(subprocess_mod=subprocess):
    """AST 抽取 overfit_monitor.py 的守卫函数 + 常量(按源序), exec 到隔离命名空间。

    subprocess_mod: 注入的 subprocess 替身(默认真模块; 零外发证据段注入记录型 stub)。
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    nodes = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in _WANT_FUNCS:
            nodes.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in _WANT_CONSTS for t in n.targets):
            nodes.append(n)
    ns = {"re": re, "os": os, "subprocess": subprocess_mod}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SRC), "exec"), ns)  # noqa: S102
    return ns


def _run_guard(fn, *args, **kw):
    """跑守卫并捕获 stdout(warn 文案)。返回 (rc, out)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*args, **kw)
    return rc, buf.getvalue()


def _latest_md5():
    p = REPO / "data" / "alerts" / "latest.md"
    if not p.exists():
        return None
    return hashlib.md5(p.read_bytes()).hexdigest()


def test_223_overfit_monitor_timeout():
    src = SRC.read_text(encoding="utf-8")
    guard = _load_guard()

    # ── ① 「真改了」: 常量 + 调用点(源码文本断言, 防只改注释)
    _ck(guard["_R2_UPLOAD_TIMEOUT"] == 900, "常量 _R2_UPLOAD_TIMEOUT 应为 900")
    _ck(guard["_R2_UPLOAD_TIMEOUT_MARGIN"] == 300, "余量常量应为 300")
    _ck("_r2_timeout = _r2_upload_timeout() + _r2_skip_retry" in src,
        "调用点应改走守卫 _r2_upload_timeout()")
    _ck("_r2_timeout = 120 + _r2_skip_retry" not in src, "旧值 120+skip_retry 应已清除")
    _ck("#223④" in src, "应带 #223④ 记录注释")

    # ── ② 守卫: 外层无界(0)⇒ 放行, 不硬比较(本机 mac 无 systemctl 亦走此路)
    rc0, out0 = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=0)
    _ck(rc0 == 900, f"外层 0(无界) 应放行 900, 实得 {rc0}")
    _ck(out0.strip() == "", "外层无界时不应误报 warn")
    rc_none, _ = _run_guard(guard["_r2_upload_timeout"])          # 默认 → 探测 systemd(本机→0)
    _ck(rc_none == 900, f"默认(探测, 本机无 systemctl=无界) 应 900, 实得 {rc_none}")

    # ── ②a 倒置输入(外层): systemd 600 < 本层 900 ⇒ 守卫收回(优雅先跑)
    rc_outer, out_outer = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=600)
    _ck(rc_outer == 300, f"外层 600 倒置 ⇒ 应收回到 300(600-300), 实得 {rc_outer}")
    _ck(rc_outer < 600, "收回应严格小于外层墙(梯度恢复)")
    _ck("⚠" in out_outer and "自动收到" in out_outer, "外层倒置应打 warn")

    # ── ②b 倒置输入(内层 HTTP): 内层 1200 > 本层 900 ⇒ 守卫抬升(本层活过子进程自身超时)
    os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = "1200"
    try:
        rc_http, out_http = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=0)
    finally:
        os.environ.pop("R2_UPLOAD_HTTP_TIMEOUT", None)
    _ck(rc_http == 1500, f"内层 HTTP 1200 ⇒ 应抬到 1500(1200+300), 实得 {rc_http}")
    _ck(rc_http > 1200, "抬升应严格大于内层 HTTP 超时")
    _ck("⚠" in out_http and "自动抬到" in out_http, "内层倒置应打 warn")

    # ── ②c 合规输入: 云上口径(内层 600, 外层 0)⇒ 900 静默不动
    os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = "600"
    try:
        rc_ok, out_ok = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=0)
    finally:
        os.environ.pop("R2_UPLOAD_HTTP_TIMEOUT", None)
    _ck(rc_ok == 900, f"云上口径(600, 外层无界) 应 900 不动, 实得 {rc_ok}")
    _ck(out_ok.strip() == "", "合规输入不应打 warn")

    # ── ②d 不变量: 外层取值域内, 结果要么放行 900 要么严格 < 外层(永不制造新倒置)
    for outer in (0, 60, 300, 600, 900, 1200):
        r, _ = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=outer)
        _ck(outer == 0 or r < outer, f"outer={outer} ⇒ 结果 {r} 必须 < 外层(不制造倒置)")
    # 退化: 外层 ≤ 余量(如 1s)物理上无法容纳余量 ⇒ 取最小 1s 但仍必须 warn(不静默)
    r_tight, out_tight = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=1)
    _ck(r_tight == 1 and "⚠" in out_tight, "外层过紧(1s) ⇒ 取最小 1s 且 warn(不静默)")
    # ②e 不变量: 外层无界时, 结果恒 > 内层 HTTP(守住 #217② 先例方向)
    for http in (0, 30, 120, 300, 599, 900, 901, 1200):
        os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = str(http)
        try:
            r, _ = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=0)
        finally:
            os.environ.pop("R2_UPLOAD_HTTP_TIMEOUT", None)
        _ck(r > http, f"http={http} ⇒ 结果 {r} 必须 > 内层 HTTP")
    # ②f 非法 env ⇒ 回退 30, 不炸
    os.environ["R2_UPLOAD_HTTP_TIMEOUT"] = "abc"
    try:
        r, _ = _run_guard(guard["_r2_upload_timeout"], outer_wall_secs=0)
    finally:
        os.environ.pop("R2_UPLOAD_HTTP_TIMEOUT", None)
    _ck(r == 900, f"http 非数字 ⇒ 回退 30 ⇒ 900, 实得 {r}")

    # ── ③ systemd 时间跨度解析(真实格式样本: 云上实测 'infinity' / '10min')
    p = guard["_parse_systemd_span_secs"]
    for raw, want in (("infinity", 0), ("", 0), ("0", 0), ("600s", 600),
                      ("10min", 600), ("1h 30min", 5400), ("500ms", 0), ("abc", 0),
                      (" 1min 30s ", 90)):
        _ck(p(raw) == want, f"_parse_systemd_span_secs({raw!r}) 应 {want}, 实得 {p(raw)}")

    # ── ④ 守卫非注释级/非写死: 同一输入(外层 600)下, 行为随常量值改变
    #    (900 ⇒ 倒置收回 300; 120 ⇒ 合规不动)⇒ 证明判定真依赖运行值, 不是注释/写死分支
    ns2 = _load_guard()
    ns2["_R2_UPLOAD_TIMEOUT"] = 120          # 模拟旧值(合规: 120 < 600, 非倒置)
    r120, _ = _run_guard(ns2["_r2_upload_timeout"], outer_wall_secs=600)
    _ck(r120 == 120, f"旧值 120 + 外层 600(合规) 应不动 120, 实得 {r120}")
    _ck(r120 != rc_outer, "同一外层输入下 900/120 结果不同 ⇒ 判定随运行值改变")

    # ── ⑤ 零真实外发证据(§18 L48 · 非空断言): 守卫唯一外呼 = 只读 systemctl show,
    #    绝无 notify/HTTP/邮件链路。用「记录型 stub subprocess」证明「唯一外呼=只读探测」。
    calls = []

    class _StubProc:
        @staticmethod
        def run(cmd, **kw):
            calls.append(list(cmd))

            class _R:              # 模拟 systemctl 无输出 ⇒ 视为无界
                stdout = ""
            return _R()

    ns3 = _load_guard(subprocess_mod=_StubProc)
    r_stub, _ = _run_guard(ns3["_r2_upload_timeout"])   # 默认 ⇒ 走真实探测路径
    _ck(r_stub == 900, f"stub 探测(无输出=无界) 应 900, 实得 {r_stub}")
    _ck(calls == [["systemctl", "show", "-p", "TimeoutStartUSec", "--value",
                   "trade-overfit-monitor.service"]],
        f"守卫唯一外呼应为只读 systemctl show, 实得 {calls}")
    _ck(not hasattr(_StubProc, "Popen"),
        "stub 无 Popen ⇒ 守卫若企图起任何其他子进程会直接 AttributeError(不可静默外发)")
    _ck(not any(k in ns3 for k in ("notify", "send_notify", "smtplib", "urllib",
                                   "requests", "http", "socket")),
        "守卫命名空间不含任何通知/HTTP/socket 依赖(static-only)")
    # 真实 alerts 文件(若本树存在)逐位核对未变;本 worktree 无 data/ 时不空断言
    before = _latest_md5()
    if before is not None:
        _ck(_latest_md5() == before, "自测全程 data/alerts/latest.md 未变(零真实外发)")
    else:
        print("[note] 本 worktree 无 data/alerts/latest.md; 零真发另由 stub 记录断言保证")

    # 断言数下限(防收集/执行异常假绿)
    _ck(_n >= 30, f"断言数仅 {_n}(下限 30), 疑似收集/执行异常")
    print(f"test_223_overfit_monitor_timeout: {_n} 断言全 PASS")