# -*- coding: utf-8 -*-
"""#223② nextday_plan_generator 内层 R2 上传超时 300→480 —— static-only 断言。

背景: #223「超时梯度」同类面。②处真触发 1 次(2026-09-30 22:30, nextday_plan_launchd.log:1642
「⚠ R2 上传超时(300s, 将告警)」, 整链 318s rc=1; 同夜 23:00 R2 rc=28 旁证)。用户 2026-10-07
拍板 300 → 480, 算式逐字见 docs/ops/223-123-inner-timeout-evidence-20261006.md §3.3:
  480 + 28(上传前 ≤10s + 超时后处理实测 18s) = 508 < 600(本链外层 systemd TimeoutStartSec), 余 92s。

本处**不采用** #217②/overfit 的运行时抬升守卫 —— 其「内层 HTTP(云上 .env=600)≥ 本层则抬升」
规则会把 480 抬过 600(越 systemd 墙, 禁止)。外层固定 600 ⇒ 480 < 600 无倒置, 改由注释 +
本测试固化「480 < 600」不变量(对齐 #6.5 少写抽象: 无第二真实使用者不造守卫)。

§18 L50(static-only): 只对源码做 ast 解析 / 文本断言, **绝不 import 业务模块、绝不 exec 脚本
主体**(该脚本带 notify.py 邮件/飞书链路 + R2 上传, 执行即可能真实外发)。零真实外发。
"""
import ast
import hashlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "scripts" / "nextday_plan_generator.py"

# 真实生产样本(§18 L49: 取自 223-123 取证报告, 非人工构造)
_OUTER_WALL = 600      # trade-nextday-plan.service TimeoutStartSec(云上实测)
_POST_TIMEOUT = 28     # 上传前 ≤10s + 超时后处理实测 18s(2026-09-30 22:35:01→22:35:19)
_TRIGGER_LOWER = 300   # 观测触发下界(2026-09-30 318s 事件 = 300 超时 + 18 收尾)

_N = 0


def _ck(cond, msg):
    global _N
    _N += 1
    assert cond, f"[#{_N}] {msg}"


def _subprocess_run_calls(tree):
    """返回 [(lineno, {kwarg: 字面量})], 只含 subprocess.run(...) 调用(ast, 不 exec)。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "run"
                and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"):
            continue
        kws = {kw.arg: kw.value.value for kw in node.keywords
               if kw.arg and isinstance(kw.value, ast.Constant)}
        out.append((node.lineno, kws))
    return out


def test_223_nextday_plan_timeout():
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)                       # 只解析, 绝不 exec / import
    lines = src.splitlines()
    calls = _subprocess_run_calls(tree)

    # ── ① 「真改了」(AST 层而非注释级): 恰有一个 subprocess.run(timeout=480)
    to480 = [ln for ln, kw in calls if kw.get("timeout") == 480]
    _ck(len(to480) == 1, f"应有恰 1 处 subprocess.run(timeout=480), 实得 {to480}")
    call_ln = to480[0]
    win = "\n".join(lines[max(0, call_ln - 20):call_ln + 1])
    _ck("upload_r2.py" in win and "upload-data-files" in win,
        "timeout=480 调用点上下文应含 upload_r2.py + upload-data-files(R2 上传点)")

    # 该调用点 timeout 必须是字面常量 480(无运行时表达式 ⇒ 结构上绝不可能抬过 600)
    call_line = lines[call_ln - 1]
    _ck(re.search(r"timeout=480\b", call_line) is not None,
        f"调用点行应为字面 timeout=480, 实得: {call_line.strip()}")
    _ck(re.search(r"timeout=\s*[A-Za-z_(]", call_line) is None,
        "调用点 timeout 不应是运行时表达式(须常量, 无抬升路径)")

    # ── ② 旧值已清除; 其余 subprocess.run 未误伤(防回归)
    _ck(all(kw.get("timeout") != 300 for _, kw in calls),
        "同文件不应残留任何 subprocess.run(timeout=300)")
    _ck("timeout=300" not in src, "源码文本不应残留 timeout=300")
    tos = sorted(kw["timeout"] for _, kw in calls if "timeout" in kw)
    _ck(tos == [60, 120, 480],
        f"同文件 subprocess.run 超时集合应为 [60,120,480](notify 60/120 未误伤), 实得 {tos}")

    # ── ③ 注释与现状一致(#223② 拍板记录, 旧「勿擅改」块已被替换, 不再矛盾)
    _ck("#223(2026-10-06) 记录(勿擅改)" not in src, "旧「勿擅改」注释块应已替换")
    _ck("#223②" in src, "应带 #223② 标记")
    _ck("2026-10-07" in win and "用户拍板" in win, "注释应含 2026-10-07 用户拍板记录")
    _ck("508" in win and "600" in win, "注释应含算式 508 与外墙 600")
    _ck("不加运行时梯度守卫" in win, "注释应写明「不加运行时梯度守卫」的判定")

    # ── ④ 日志/告警文案同步(300s → 480s, 三处口径一致, §22)
    _ck("R2 上传超时(480s, 将告警)" in src, "TimeoutExpired 日志应改为 480s")
    _ck("R2 上传超时(300s" not in src, "旧 300s 超时日志应已清除")
    _ck("R2 upload-data-files 480s 超时" in src, "severe 告警文案应改为 480s")
    _ck("R2 upload-data-files 300s 超时" not in src, "旧 300s severe 文案应已清除")

    # ── ⑤ 不变量 + 算式复算(用真实生产样本)
    _INNER = 480
    _ck(_INNER < _OUTER_WALL,
        f"内层 {_INNER} 必须 < 外层 systemd {_OUTER_WALL}(不越墙 ⇒ 保优雅超时先于 SIGKILL)")
    _ck(_INNER + _POST_TIMEOUT == 508,
        f"算式复算 480+{_POST_TIMEOUT} 应 =508, 实得 {_INNER + _POST_TIMEOUT}")
    _ck(_INNER + _POST_TIMEOUT < _OUTER_WALL,
        f"508 应 < 外层 {_OUTER_WALL}(余 {_OUTER_WALL - 508}s)")
    _ck(_INNER > _TRIGGER_LOWER,
        f"480 应 > 触发下界 {_TRIGGER_LOWER}(否则未覆盖已触发带)")

    # ── ⑥ 零真实外发证据(§18 L48 · 非空): 本测试不 import 业务模块 / 不调任何子进程
    self_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(self_tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    _ck("nextday_plan_generator" not in imported, "本测试不得 import 业务模块")
    _ck("subprocess" not in imported, "本测试 static-only: 不 import/调任何子进程")
    _ck("notify" not in imported and "smtplib" not in imported,
        "本测试不 import 任何通知链路(邮件/飞书/socket)")
    latest = REPO / "data" / "alerts" / "latest.md"
    if latest.exists():
        h_before = hashlib.md5(latest.read_bytes()).hexdigest()
        _ck(SRC.read_text(encoding="utf-8") == src, "断言期间源文件不应被改写")
        _ck(hashlib.md5(latest.read_bytes()).hexdigest() == h_before,
            "自测全程 data/alerts/latest.md 未变(零真实外发)")
    else:
        print("[note] 本 worktree 无 data/alerts/latest.md; 零真发由 static-only(AST-only 无 exec)保证")

    # 断言数下限(防收集/执行异常假绿)
    _ck(_N >= 20, f"断言数仅 {_N}(下限 20), 疑似收集/执行异常")
    print(f"test_223_nextday_plan_timeout: {_N} 断言全 PASS")