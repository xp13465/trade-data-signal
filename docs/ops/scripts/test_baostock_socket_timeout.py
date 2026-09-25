"""baostock_socket_timeout 单元测试(2026-09-25 P0 修复验证, C1/C3 补强版)。

覆盖:
1. _apply_timeout_to_default_socket 对已有 socket 设 timeout
2. _send_msg_patched: send 成功之后对端才关写端 -> recv 返回 b"" -> 有限时间返 None
   (9-24 生产事故真实时序; 原实现此场景无限空转)
2b. 对照: 原版 send_msg 循环(无 b"" 守卫)在同一时序下 1s 仍空转不退出
3. apply_socket_timeout 幂等 + 替换 SocketUtil.connect/get_default_socket/send_msg
   + socket 模块属性不被替换(常量引用不破坏)
4. patch 后真实 baostock login 建的 socket 带 timeout(本地可连则验, 连不上自动跳过)
"""
import os
import sys
import time

# C3: 可移植仓库根推导(不硬编码 worktree 绝对路径; 可用 TRADE_REPO_ROOT 覆盖)
_REPO_ROOT = os.environ.get("TRADE_REPO_ROOT")
if not _REPO_ROOT:
    _REPO_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )
if not os.path.isdir(os.path.join(_REPO_ROOT, "app")):
    raise SystemExit(
        f"[FATAL] 仓库根推导失败(未见 app/ 目录): {_REPO_ROOT} "
        f"(测试脚本须位于 <repo>/docs/ops/scripts/ 下, 或设 TRADE_REPO_ROOT)"
    )
sys.path.insert(0, _REPO_ROOT)

from app.collector import baostock_socket_timeout as mod
from app.collector.baostock_socket_timeout import (
    _apply_timeout_to_default_socket, _send_msg_patched,
    apply_socket_timeout, BAOSTOCK_SOCK_TIMEOUT,
)
import socket as _s
import baostock.common.context as _ctx

# 1. _apply_timeout_to_default_socket
_sock = _s.socket()
_sock.settimeout(None)
_prev = getattr(_ctx, "default_socket", None)
_ctx.default_socket = _sock
_apply_timeout_to_default_socket()
assert _sock.gettimeout() == BAOSTOCK_SOCK_TIMEOUT, _sock.gettimeout()
_sock.close()
_ctx.default_socket = _prev
print(f"[PASS] 1. _apply_timeout_to_default_socket timeout={BAOSTOCK_SOCK_TIMEOUT}")

# 2. recv-b"" 守卫(9-24 真实事故形态: send 成功之后对端才关写端)
#    b.shutdown(SHUT_WR) 后 a.send() 仍成功(对端读端仍开), 但 a.recv() 读到 EOF -> b"";
#    原版循环对 b"" 无限空转, patch 版 `if not chunk: return None` 有限返回。
#    (C1 修正: 此前用 b.close() 先关对端, 实际触发 send-BrokenPipe 分支, 测不到守卫)
a, b = _s.socketpair()
b.shutdown(_s.SHUT_WR)  # 对端只关写端(不是 close), 保证 send 成功、recv 才见 EOF
_prev = getattr(_ctx, "default_socket", None)
_ctx.default_socket = a
try:
    t0 = time.time()
    r = _send_msg_patched("test-msg")
    dt = time.time() - t0
    assert r is None, f"应返 None, 实际 {r!r}"
    assert dt < 2.0, f"应快速返回(不空转), 实际 {dt:.1f}s"
    print(f"[PASS] 2. send 成功后对端关写端 -> recv 返 b\"\" -> send_msg 返 None, {dt*1000:.0f}ms(不空转)")
finally:
    a.close()
    b.close()
    _ctx.default_socket = _prev

# 2b. 对照: 原版 send_msg 循环(无 b"" 守卫)同一时序下 1s 高速空转不退出
#     证明「原版无限空转 / patch 版有限返回」的真实对比(C1 防回归关键)。
a2, b2 = _s.socketpair()
b2.shutdown(_s.SHUT_WR)
import threading
_res = {"n": 0}

def _run_orig():
    """忠实复刻原版 baostock.util.socketutil.send_msg 的 recv 循环(无 b"" 守卫)。
    忙循环中实时累加计数(循环永不退出, 故计数只在循环体内更新)。"""
    _a = a2
    receive = b""
    while True:
        try:
            chunk = _a.recv(8192)
        except OSError:
            break  # 主线程已 close 对照 socket, 结束对照线程(忙循环特征已计入计数)
        _res["n"] += 1
        receive += chunk
        if receive[-13:] == b"<![CDATA[]]>\n":
            break

t = threading.Thread(target=_run_orig, daemon=True)
t.start()
t.join(1.0)
_alive = t.is_alive()
_n = _res.get("n", 0)
a2.close()
b2.close()
assert _alive, "原版模拟应在同一时序空转不退出(1s 后仍 alive)"
assert _n > 100, f"原版模拟应高速忙循环, 实际 1s 仅 {_n} 次"
print(f"[PASS] 2b. 对照: 原版 send_msg 同时序 1s 空转 {_n} 次仍不退出 vs patch 版 0ms 返 None")

# 3. apply 幂等 + 替换 + socket 模块属性不破坏
mod._patched = False
import baostock.util.socketutil as sutil
_orig_connect = sutil.SocketUtil.connect
_orig_get_default = sutil.get_default_socket
_orig_send_msg = sutil.send_msg
apply_socket_timeout()
assert sutil.SocketUtil.connect is not _orig_connect, "connect 未替换"
assert sutil.get_default_socket is not _orig_get_default, "get_default_socket 未替换"
assert sutil.send_msg is mod._send_msg_patched, "send_msg 未替换"
assert sutil.socket is _s, "socket 模块属性不应被替换(防常量引用破坏)"
# 幂等
first = mod._patched
apply_socket_timeout()
assert mod._patched and first
print("[PASS] 3. apply 幂等 + connect/get_default_socket/send_msg 已替换, socket 属性未动")

# 4. 真实 login(本地可连则验; 连不上自动跳过, 云上已验证 timeout=30)
import baostock as bs
lg = bs.login()
if lg.error_code != "0":
    print("[SKIP] 4. 本地网络连不上 baostock(login 失败), 真实 login 验证在云上执行")
else:
    so = getattr(_ctx, "default_socket", None)
    assert so is not None and so.gettimeout() == BAOSTOCK_SOCK_TIMEOUT, \
        f"login socket timeout={so.gettimeout() if so else None}"
    bs.logout()
    print(f"[PASS] 4. baostock login 建 socket timeout={BAOSTOCK_SOCK_TIMEOUT}")

print("\nALL PASS")
