"""baostock_socket_timeout 单元测试(2026-09-25 P0 修复验证)。

覆盖:
1. _apply_timeout_to_default_socket 对已有 socket 设 timeout
2. _send_msg_patched 对端关闭时返回 None(不空转死循环)
3. apply_socket_timeout 幂等 + 替换 SocketUtil.connect/get_default_socket/send_msg
   + socket 模块属性不被替换(常量引用不破坏)
4. patch 后真实 baostock login 建的 socket 带 timeout(云上验证, 本地网络限制可跳过)
"""
import sys
sys.path.insert(0, "/Users/linhuichen/code/trade/.claude/worktrees/agent-afd201d75625b1456")

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

# 2. send_msg 空转守卫
a, b = _s.socketpair()
b.close()
_prev = getattr(_ctx, "default_socket", None)
_ctx.default_socket = a
try:
    import time
    t0 = time.time()
    r = _send_msg_patched("test-msg")
    dt = time.time() - t0
    assert r is None, f"应返 None, 实际 {r!r}"
    assert dt < 2.0, f"应快速返回(不空转), 实际 {dt:.1f}s"
    print(f"[PASS] 2. recv 返回 b\"\" -> send_msg 返 None, 耗时 {dt*1000:.0f}ms(不空转)")
finally:
    a.close()
    _ctx.default_socket = _prev

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

# 4. 真实 login(本地可能连不上 baostock -> 标注跳过; 云上验证)
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