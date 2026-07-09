"""采集基础设施：限频、重试、日志、绕过系统代理。"""
import os
import random
import time
from datetime import datetime

import requests

from ..db import get_conn

# 绕过 macOS 系统代理（Clash 把东财流量走境外会被东财封 IP）。
# 国内数据源直连即可；requests 默认会 pick up 系统代理，这里全局关闭。
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

# 申万一级指数源 swsresearch.com 本地 DNS 解析失败（SERVFAIL，2026-07 实测），
# 但公共 DNS（8.8.8.8）能解析。index_hist_sw / index_realtime_sw 走该域，
# 这里 monkey-patch socket.getaddrinfo 把 swsresearch.com 解析到公共 DNS 返回的 IP。
import socket as _socket
_orig_getaddrinfo = _socket.getaddrinfo


def _resolve_sws_ip():
    """解析 swsresearch.com IP：本地 DNS 失败则试 dig @8.8.8.8，最后 fallback 固定 IP。"""
    try:  # 1. 本地 DNS（若用户修了 DNS 直接通）
        res = _orig_getaddrinfo("www.swsresearch.com", 443)
        if res:
            return res[0][4][0]
    except Exception:  # noqa: BLE001
        pass
    try:  # 2. dig @8.8.8.8（绕过本地 DNS）
        import subprocess
        r = subprocess.run(["dig", "+short", "www.swsresearch.com", "@8.8.8.8"],
                           capture_output=True, text=True, timeout=5)
        ip = r.stdout.strip().split("\n")[0].strip()
        if ip and not ip.startswith(";"):
            return ip
    except Exception:  # noqa: BLE001
        pass
    return "202.122.119.203"  # 3. fallback 固定 IP（2026-07-06 实测）


_SWS_IP = _resolve_sws_ip()


def _patched_getaddrinfo(host, port, *a, **kw):
    if host and "swsresearch.com" in host and _SWS_IP:
        return _orig_getaddrinfo(_SWS_IP, port, *a, **kw)
    return _orig_getaddrinfo(host, port, *a, **kw)


_socket.getaddrinfo = _patched_getaddrinfo

_orig_session_init = requests.Session.__init__


def _session_init(self, *a, **kw):
    _orig_session_init(self, *a, **kw)
    self.trust_env = False  # 忽略环境代理


requests.Session.__init__ = _session_init

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_LAST_CALL = [0.0]
THROTTLE_SEC = 0.6


def throttle() -> None:
    now = time.time()
    gap = now - _LAST_CALL[0]
    if gap < THROTTLE_SEC:
        time.sleep(THROTTLE_SEC - gap)
    _LAST_CALL[0] = time.time()


def direct_session() -> requests.Session:
    """直连 session（trust_env=False + 浏览器 UA），用于直爬东财。"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    return s


# ── 东财防封：全局节流 + 会话复用 + 重试（抄自 a-stock-data SKILL.md）─────────
# 东财风控阈值：>5次/秒、并发≥10、1分钟≥200次 → 封 IP。em_get 串行 1s+抖动+重试。
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception:  # noqa: BLE001
    pass
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]


def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求：1s 串行限流 + 复用 session + 指数退避重试。所有 eastmoney.com 请求走这里。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def log_collect(run_date: str, metric_id: str, status: str, message: str = "") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO collect_log (run_date, metric_id, status, message, run_at) "
        "VALUES (?,?,?,?,?)",
        (run_date, metric_id, status, (message or "")[:500], datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def safe_call(fn, retries: int = 2, **kwargs):
    """调用函数，失败重试。返回结果或异常对象（由调用方判断）。

    连接类错误（ConnectionError/RemoteDisconnected/Timeout）用更长退避(2-5s)，
    避免在远端过载时雪上加霜；其他错误用标准退避(0.8s)。
    """
    import random
    last_err = None
    for i in range(retries + 1):
        try:
            throttle()
            return fn(**kwargs) if kwargs else fn()
        except Exception as e:  # noqa: BLE001
            last_err = e
            ename = type(e).__name__
            msg = str(e)
            if any(kw in ename or kw in msg for kw in (
                "Connection", "RemoteDisconnected", "Timeout", "ProtocolError",
            )):
                time.sleep(random.uniform(2, 5) * (i + 1))
            else:
                time.sleep(0.8 * (i + 1))
    return last_err
