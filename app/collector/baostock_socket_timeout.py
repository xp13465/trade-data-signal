"""BaoStock socket 超时保护(2026-09-25 生产采集卡死 P0 根治, 告警 turnover_backfill exit=124)。

根因
====
baostock 库 socketutil.py 的 send_msg 里 recv 是无限循环, 且 socket 未显式 settimeout:

    while True:
        recv = default_socket.recv(8192)
        receive += recv
        if receive[-13:] == b"<![CDATA[]]>\n":
            break

两种挂起路径都会导致 worker 永久卡死("alive" 但不推进, 无任何日志):

1) recv **阻塞不返回**(服务端半开连接, 不响应也不关闭) -> recv 永久阻塞。
   base.py 的 socket.setdefaulttimeout(30) 能兜底(阻塞 30s 抛 socket.timeout,
   baostock 内部 except 吞掉返回 None -> query 返 10002007 -> 我方断线重连自愈)。
   但 setdefaulttimeout 依赖"未显式 settimeout 的新 socket", 一旦有人显式
   settimeout(None) 或建 socket 前 default 被改, 该兜底失效。

2) recv 返回 b""(服务端正常关闭连接/连接被重置) -> 循环立即再次 recv 返回 b"",
   **不抛异常、不阻塞、无限空转**(CPU 100%, 零日志, socket.timeout 完全不触发)。
   9-24 晚实证就是这一条: 诊断确认 worker 进程 socket 带 30s timeout, 若真是
   recv 阻塞必有 30s 级超时日志; 实际是 21:14 后 120 分钟零输出, 只有 recv 返回
   b"" 空转符合全部特征。

9-24 晚时间线: turnover_backfill 21:10 启动, worker 处理到 180/5200 后连接被服务端
关闭, recv 返回 b"" 空转 120 分钟, pipeline 监控刷 "100/5200 codes done, 1/1 workers
alive" 后被 7200s 超时 kill(exit=124)。当日换手率增量只采到 100/5200(98% 断更)。

修复
====
monkey-patch baostock.util.socketutil 模块(模块单例, 一处替换全局生效):

- SocketUtil.connect / get_default_socket(baostock 包内仅这两处建 socket, grep 实证)
  -> 建连后显式 settimeout(recv/connect 均受保护, 不依赖 setdefaulttimeout 可能被改)
  ⚠️ 不替换 socketutil.socket 模块属性——直接替换会连带破坏 socket.AF_INET/SOCK_STREAM
  等常量引用(socketutil 内部用 socket.XXX), login 抛 AttributeError, 已实证。
- send_msg -> 补 `if not chunk: return None` 守卫(recv 返回 b"" 不再空转,
  返回 None -> query 返 10002007 -> 我方 _reconnect_with_retry 重建 socket 自愈,
  根治情况 2)

超时/空转后的自愈链: recv 异常或空 -> baostock 返回 None -> query_history_k_data_plus
返回 BSERR_RECVSOCK_FAIL("10002007") -> 调用方(baostock_daily.fetch_one 等)识别网络
错误码走 _reconnect_with_retry 重建 socket 后重试, 不再永久卡死。

覆盖: 所有直接 import baostock 发 query 的采集链路
(baostock_daily / baostock_worker / mootdx_daily / public_fund / hkex_ccass_quarterly /
 index_backfill)。

用法: 入口模块在 import baostock 后调用 apply_socket_timeout()(幂等, 可重复调用)。
"""
from __future__ import annotations

import os
import socket as _socket
import zlib as _zlib

# 单次 recv/connect 超时秒数。正常 baostock 响应 <1s, 30s 足够宽松(仅挂起时才触发)。
# 可用环境变量 BAOSTOCK_SOCK_TIMEOUT 覆盖(如高延迟网络调大)。
BAOSTOCK_SOCK_TIMEOUT = float(os.environ.get("BAOSTOCK_SOCK_TIMEOUT", "30"))

_patched = False


def _apply_timeout_to_default_socket() -> None:
    """给 baostock 当前 default_socket 显式 settimeout(兜底 setdefaulttimeout 被第三方改掉)。"""
    try:
        import baostock.common.context as _ctx
        s = getattr(_ctx, "default_socket", None)
        if s is not None:
            s.settimeout(BAOSTOCK_SOCK_TIMEOUT)
    except Exception:  # noqa: BLE001
        pass


def _send_msg_patched(msg):
    """与 baostock.util.socketutil.send_msg 同行为, 补两个根因守卫:

    - recv 返回 b""(对端关闭连接) -> 返回 None, 不再空转死循环;
    - socket 带 settimeout(由 _socket_with_timeout 保证), recv 阻塞超时抛
      socket.timeout -> 被下方 except 吞掉返回 None。
    None 返回后 baostock query 层转 10002007, 调用方走断线重连自愈。
    """
    import baostock.common.contants as _cons
    import baostock.common.context as _ctx
    try:
        if hasattr(_ctx, "default_socket"):
            default_socket = getattr(_ctx, "default_socket")
            if default_socket is not None:
                msg = msg + "\n"  # 消息结尾分隔符(不压缩时)
                default_socket.send(bytes(msg, encoding="utf-8"))
                receive = b""
                while True:
                    chunk = default_socket.recv(8192)
                    if not chunk:
                        # 对端关闭连接: recv 返回 b"" 而非抛异常, 原实现无限空转
                        # (9-24 卡死 120min 根因) -> 返回 None 走断线自愈
                        return None
                    receive += chunk
                    if receive[-13:] == b"<![CDATA[]]>\n":  # 压缩时结尾分隔符
                        break
                head_bytes = receive[0:_cons.MESSAGE_HEADER_LENGTH]
                head_str = bytes.decode(head_bytes)
                head_arr = head_str.split(_cons.MESSAGE_SPLIT)
                if head_arr[1] in _cons.COMPRESSED_MESSAGE_TYPE_TUPLE:
                    # 消息体需要解压
                    head_inner_length = int(head_arr[2])
                    body_str = bytes.decode(_zlib.decompress(
                        receive[_cons.MESSAGE_HEADER_LENGTH:
                                _cons.MESSAGE_HEADER_LENGTH + head_inner_length]))
                    return head_str + body_str
                return bytes.decode(receive)
            return None
        print("you don't login.")
        return None
    except Exception as ex:  # noqa: BLE001
        print(ex)
        print("接收数据异常，请稍后再试。")
        return None


def apply_socket_timeout() -> None:
    """幂等 monkey-patch: baostock socket 一律带 settimeout + recv 空转守卫。

    只 patch 两个建 socket 点(SocketUtil.connect / get_default_socket)与 send_msg,
    不替换 socketutil.socket 模块属性(直接替换会连带破坏 socket.AF_INET 等常量引用,
    导致 login 抛 AttributeError)。baostock 包内建 socket 仅这两处(grep 实证)。

    只需执行一次(baostock.util.socketutil 是模块单例, 替换其函数即全局生效);
    多入口重复调用安全(打标短路)。未安装 baostock 的环境静默跳过(无需 patch)。
    """
    global _patched
    if _patched:
        return
    try:
        import baostock.util.socketutil as _bs_sockutil
    except ImportError:
        _patched = True  # 无 baostock -> 无需再试
        return

    _orig_connect = _bs_sockutil.SocketUtil.connect
    _orig_get_default = _bs_sockutil.get_default_socket

    def _connect_with_timeout(self):
        # 原 connect 已继承 setdefaulttimeout(connect 阶段有兜底), 建连后显式
        # settimeout(recv 阶段不依赖 default 可能被第三方改掉)。
        _orig_connect(self)
        _apply_timeout_to_default_socket()

    def _get_default_with_timeout():
        s = _orig_get_default()
        if s is not None:
            s.settimeout(BAOSTOCK_SOCK_TIMEOUT)
        return s

    _bs_sockutil.SocketUtil.connect = _connect_with_timeout
    _bs_sockutil.get_default_socket = _get_default_with_timeout
    _bs_sockutil.send_msg = _send_msg_patched
    _patched = True
