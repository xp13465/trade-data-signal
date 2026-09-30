#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rt_relay.py — 云服务器多源行情中转服务(前端替补源,非首选;对着「生产采集 IP 安全第一」设计)

背景(2026-09-30 用户拍板):
  东财 trends2 间歇性拒绝(本机/云上成功率均 3/10,服务端问题非 IP 封禁);
  腾讯 minute/query 对北交所只返 3 段(另一单在修前端容错);
  新浪 hq.sinajs.cn/quotes.sina.cn 数据可取但**无 ACAO 头** → 浏览器直连被 CORS 拦,
     只有服务端能当源 —— 这正是中转服务的核心增量。
  因此做:云上多源(东财/腾讯/新浪)聚合 + 负载均衡 + 熔断 + 限速 + 短缓存,
         中转为浏览器的一个**替补源**(前端"东财→腾讯→中转"第三腿)。

端口/通道: 云上监听 8080 明文 HTTP,HTTPS 由 CF 边缘提供(CF 免费版回源支持 8080)。

安全(最高优先级): 本服务部署在**生产采集 IP** 上,任何上游请求都可能在风控视野内。
  - 每源 token bucket 限速 + 全局上游限速 + 全局并发上限;
  - 源/主机级熔断(确定性拒绝≠偶发抖动分档),已坏的源短路不反复打;
  - 主机级冷却:失败主机单独退避,断源状态下不放大请求量。

零依赖: 仅标准库(urllib/http.server/threading),Python 3.10+ 可跑。

启动方案(只写不执行,详情见 relay/README.md):
  手动:       python3 relay/rt_relay.py --port 8080
  nohup:      nohup python3 relay/rt_relay.py >> /var/log/rt_relay.log 2>&1 &
  systemd:    见 README 的 rt_relay.service 单元示例(云上手动管理,不走 git)
"""

import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ------------------------------------------------------------------ 配置

PORT = int(os.environ.get("RT_PORT", "8080"))
BIND = os.environ.get("RT_BIND", "0.0.0.0")
CACHE_TTL = float(os.environ.get("RT_CACHE_TTL", "4"))          # 4s 短缓存(多用户共享)
PRE_CLOSE_TTL = float(os.environ.get("RT_PRE_CLOSE_TTL", "21600"))  # 新浪昨收缓存 6h(日内不变)
UPSTREAM_TIMEOUT = float(os.environ.get("RT_TIMEOUT", "8"))     # 上游请求超时 8s
CONCURRENCY = int(os.environ.get("RT_CONCURRENCY", "6"))        # 全局上游并发上限
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# CORS 允许来源: 默认 * (公开行情数据,无凭据,无私有数据; 生产可改 RT_ORIGINS 收窄)
_ALLOWED_ORIGINS = [s.strip() for s in os.environ.get("RT_ORIGINS", "*").split(",") if s.strip()]

# 源启用开关(逗号列表,运营可用; 测试可只留 sina 构造"只剩新浪"场景)
_DEFAULT_SOURCES = {"em", "qq_min", "sina", "qq_day"}
_RT_SOURCES = set(s.strip() for s in os.environ.get("RT_SOURCES", ",".join(sorted(_DEFAULT_SOURCES))).split(",") if s.strip())

# 熔断参数(测试可用环境变量收紧时长)
BREAKER_DET_N = int(os.environ.get("RT_DET_N", "3"))          # 确定性拒绝连续N次→熔断
BREAKER_NET_N = int(os.environ.get("RT_NET_N", "6"))          # 网络抖动连续N次→熔断
BREAKER_OPEN_DET = float(os.environ.get("RT_OPEN_DET", "60"))  # 确定性拒绝熔断时长
BREAKER_OPEN_NET = float(os.environ.get("RT_OPEN_NET", "45"))  # 抖动熔断时长

# 测试注入: RT_TEST_DET_FAIL=em  → em 恒抛确定性拒绝(实测熔断用,默认空)
_TEST_DET_FAIL = set(s.strip() for s in os.environ.get("RT_TEST_DET_FAIL", "").split(",") if s.strip())

# ------------------------------------------------------------------ 指数映射
# 与前端 app.js 同构(static-site/app.js:12492 _INDEX_TO_TENCENT_MINUTE / 12499 _INDEX_TO_EASTMONEY_SECID)
INDEX_QQ = {
    "sh": "sh000001", "sz": "sz399001", "hs300": "sh000300", "sz50": "sh000016",
    "cyb": "sz399006", "kc50": "sh000688", "bj50": "bj899050",
    "csi500": "sh000905", "csi1000": "sh000852",
    "hsi": "hkHSI", "hstech": "hkHSTECH", "hscei": "hkHSCEI",
}
INDEX_EM = {
    "sh": "1.000001", "sz": "0.399001", "hs300": "1.000300", "sz50": "1.000016",
    "cyb": "0.399006", "kc50": "1.000688", "bj50": "0.899050",
    "csi500": "1.000905", "csi1000": "1.000852",
    "hsi": "100.HSI", "hstech": "124.HSTECH", "hscei": "100.HSCEI",
}
# 新浪仅 A 股(实测港股 rt_hkHSI 返回 null,不支持)
INDEX_SINA = {
    "sh": "sh000001", "sz": "sz399001", "hs300": "sh000300", "sz50": "sh000016",
    "cyb": "sz399006", "kc50": "sh000688", "bj50": "bj899050",
    "csi500": "sh000905", "csi1000": "sh000852",
}

# ------------------------------------------------------------------ 上游源定义
# 主机级负载均衡: 每源多 base 轮流(与前端 _EM_HOSTS/_QQ_HOSTS 同构), 失败主机各自冷却

def _em_urls(secid):
    hosts = ["push2delay.eastmoney.com", "push2.eastmoney.com", "2.push2.eastmoney.com",
             "10.push2.eastmoney.com", "20.push2.eastmoney.com"]
    path = ("/api/qt/stock/trends2/get?secid={}&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,"
            "f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58&iscr=0&ndays=1&_={}")
    ts = int(time.time() * 1000)
    return [("em#" + h, "https://" + h + path.format(secid, ts)) for h in hosts]

def _qq_urls(qqcode, kind):
    bases = ["web.ifzq.gtimg.cn", "proxy.finance.qq.com/ifzq", "ifzq.finance.qq.com"]
    p = "minute" if kind == "min" else "day"
    return [("qq_%s#%s" % (kind, b), "https://%s/appstock/app/%s/query?code=%s" % (b, p, qqcode))
            for b in bases]

def _sina_urls(sym, scale, datalen):
    base = "quotes.sina.cn"
    path = ("/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
            "?symbol={}&scale={}&ma=no&datalen={}")
    return [("sina_%d#%s" % (scale, base), "https://" + base + path.format(sym, scale, datalen))]

SOURCE_ORDER = ["em", "qq_min", "sina", "qq_day"]          # 主解析优先级
# (req/min, burst) —— 限速依据(见 README 安全核算):
#   前端注释既有风控边界: 同花顺<30/东财<60/腾讯<40 每分; 本服务取边界内保守值。
#   真实需求: 12 codes × 1/min 使用量级; 全降级只走新浪 = 12~24/min。
RATE_LIMITS = {
    "em":      (40, 10),   # 东财边界 60 → 取 40
    "qq_min":  (30, 8),    # 腾讯边界 40 → 取 30
    "qq_day":  (20, 6),    # day/query 与 min 同源族, 合计仍 < 40
    "sina":    (40, 10),   # 新浪宽松, 保守 40
    "sina_day": (10, 4),   # 昨收辅助, 按 code 按日缓存, 用量几乎为零
}
GLOBAL_LIMIT, GLOBAL_BURST = 120, 30   # 全局上游总请求/分 硬上限
_CACHE_MAX = 1000                      # 缓存条目上限(溢出清最旧)

# ------------------------------------------------------------------ 工具

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def _fmt_qq_date(d):
    """20260930 -> 2026-09-30"""
    if d and len(d) == 8 and d.isdigit():
        return "%s-%s-%s" % (d[:4], d[4:6], d[6:8])
    return d or ""

def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _log(obj):
    obj["ts"] = _now()
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass

# ------------------------------------------------------------------ 限速: 令牌桶
class TokenBucket:
    def __init__(self, rate_per_min, burst):
        self.cap = float(burst)
        self.tokens = float(burst)
        self.rate = rate_per_min / 60.0
        self.last = time.monotonic()
        self.lock = threading.Lock()
        self.recent = deque()   # 最近 take 时刻(仅 /health 展示近 60s 用量)

    def take(self, n=1):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.cap, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= n:
                self.tokens -= n
                self.recent.append(now)
                return True
            return False

    def used_last_60s(self):
        now = time.monotonic()
        with self.lock:
            while self.recent and now - self.recent[0] > 60:
                self.recent.popleft()
            return len(self.recent)

# ------------------------------------------------------------------ 熔断: 区确定性拒绝 vs 偶发抖动
class DeterministicReject(Exception):
    """确定性拒绝: 上游服务器明确说了「不给你」或「无数据」(业务拒/4xx/5xx/非预期结构)"""

class NetJitter(Exception):
    """偶发抖动: 传输层错误/超时/连接重置"""

class Breaker:
    def __init__(self, name):
        self.name = name
        self.lock = threading.Lock()
        self.state = "closed"            # closed | open | half_open
        self.det_cnt = 0
        self.net_cnt = 0
        self.until = 0.0
        self.opened_at = 0.0
        self.trips = 0
        self.ok = 0
        self.det_fail = 0
        self.net_fail = 0

    def allow(self):
        with self.lock:
            now = time.monotonic()
            if self.state == "open":
                if now >= self.until:
                    self.state = "half_open"   # 放行一次探测(半开)
                    return True
                return False
            if self.state == "half_open":
                return False                   # 探测中, 其余请求仍跳过
            return True

    def record(self, ok, det=True):
        with self.lock:
            now = time.monotonic()
            if ok:
                self.det_cnt = 0
                self.net_cnt = 0
                self.state = "closed"
                self.until = 0.0
                self.ok += 1
                return
            if det:
                self.det_cnt += 1
                self.det_fail += 1
                th, dur = BREAKER_DET_N, BREAKER_OPEN_DET
            else:
                self.net_cnt += 1
                self.net_fail += 1
                th, dur = BREAKER_NET_N, BREAKER_OPEN_NET
            if self.state == "half_open":
                # 半开探测失败: 立即重回 open(拉满时长)
                self.state = "open"
                self.until = now + dur
                self.trips += 1
                self.opened_at = now
                return
            if self.det_cnt >= th or self.net_cnt >= BREAKER_NET_N:
                # 两种计数任一超阈值即打开(阈值按对应档位)
                self.state = "open"
                self.until = now + dur
                self.trips += 1
                self.opened_at = now

    def info(self):
        with self.lock:
            return {
                "state": self.state, "trips": self.trips, "ok": self.ok,
                "det_fail": self.det_fail, "net_fail": self.net_fail,
                "det_cnt": self.det_cnt, "net_cnt": self.net_cnt,
                "open_until_s": max(0.0, self.until - time.monotonic()) if self.state == "open" else 0.0,
            }

BREAKERS = {name: Breaker(name) for name in RATE_LIMITS}
BUCKETS = {name: TokenBucket(*rl) for name, rl in RATE_LIMITS.items()}
GLOBAL_BUCKET = TokenBucket(GLOBAL_LIMIT, GLOBAL_BURST)
_CONC_SEM = threading.BoundedSemaphore(max(1, CONCURRENCY))
_conc_now = 0
_conc_peak = 0
_conc_lock = threading.Lock()

# ------------------------------------------------------------------ 主机级冷却(断源不放大请求)
_COOL_DET_S, _COOL_NET_S = 60.0, 45.0
_host_cool = {}
_host_cool_lock = threading.Lock()

def _host_cooled(key):
    with _host_cool_lock:
        return _host_cool.get(key, 0.0) > time.monotonic()

def _mark_host(key, det):
    with _host_cool_lock:
        _host_cool[key] = time.monotonic() + (_COOL_DET_S if det else _COOL_NET_S)

# ------------------------------------------------------------------ 上游 HTTP 抓取
_SSL_CTX = ssl.create_default_context()
_SSL_CTX_INSECURE = ssl._create_unverified_context()

def _urlopen(req):
    """先按证书验证抓取; 国内 CDN 链不全(或机器 CA 未装)时报 SSL 错 → 降级无验重试一次。
    公开行情数据, 无凭据无私有信息; 云上装好 ca-certificates 的正常环境走验证路径不触发。"""
    try:
        return urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT)
    except urllib.error.URLError as e:
        # urlopen 把底层 SSL 错包进 URLError.reason
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            _log({"evt": "ssl-insecure-fallback", "why": str(e.reason)[:80], "url": url_str(req)})
            return urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT, context=_SSL_CTX_INSECURE)
        raise

def url_str(req):
    try:
        return req.full_url
    except AttributeError:
        return req.get_full_url()

def _get_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://finance.sina.com.cn/",
        "Connection": "close",
    })
    try:
        with _urlopen(req) as resp:
            status = resp.status
            body = resp.read()
        if status == 204:
            raise DeterministicReject("http204")
        if status != 200:
            raise DeterministicReject("http%d" % status)
        try:
            return json.loads(body)
        except Exception:
            raise DeterministicReject("bad-json")
    except DeterministicReject:
        raise
    except urllib.error.HTTPError as e:
        raise DeterministicReject("http%d" % e.code)
    except (socket.timeout, TimeoutError):
        raise NetJitter("timeout")
    except ConnectionError as e:
        raise NetJitter("conn:%s" % (getattr(e, "reason", e) or ""))
    except urllib.error.URLError as e:
        raise NetJitter("url:%s" % (getattr(e, "reason", e) or ""))
    except OSError as e:
        raise NetJitter("os:%s" % (e.strerror or e))
    except Exception as e:
        raise NetJitter("unk:%s" % str(e)[:60])

def _host_loop(urls, fn):
    """串行遍历 urls(带主机冷却跳过), fn(url) 返回最终解析数据或抛异常; 全败抛最后异常"""
    last = None
    for hkey, url in urls:
        if _host_cooled(hkey):
            continue
        try:
            return fn(url)
        except DeterministicReject as e:
            _mark_host(hkey, True)
            last = e
        except NetJitter as e:
            _mark_host(hkey, False)
            last = e
    if last is None:
        raise DeterministicReject("no-host")
    raise last

# ------------------------------------------------------------------ 各源解析适配器
def fetch_em(code):
    secid = INDEX_EM[code]

    def _fn(url):
        js = _get_json(url)
        if not isinstance(js, dict) or js.get("rc") != 0:
            raise DeterministicReject("rc!=0")
        d = js.get("data")
        if not isinstance(d, dict) or not d.get("trends"):
            raise DeterministicReject("no-data")
        pts = []
        first_date = None
        for line in d["trends"]:
            p = str(line).split(",")
            if len(p) < 7:
                continue
            dt = p[0].split(" ")
            if len(dt) < 2:
                continue
            if first_date is None:
                first_date = dt[0]
            price = _f(p[4])
            if price is None:
                continue
            pts.append({"time": dt[1], "price": price,
                        "volume": int(_f(p[5]) or 0), "amount": float(p[6] or 0)})
        if not pts:
            raise DeterministicReject("empty-points")
        pre = d.get("preClose")
        return {"name": d.get("name") or "", "price": pts[-1]["price"],
                "preClose": _f(pre) if pre is not None else None,
                "date": first_date or "", "points": pts}

    return _host_loop(_em_urls(secid), _fn)

def _parse_qq_lines(lines):
    """腾讯分钟行: "0930 1036.13 56814"(3段) 或 "0930 1036.13 56814 12345"(4段,含额)。
    北交所为纯3段, 必须容错(前端L12671在修的是值判据, 本服务从解析层直接兼容3段)。"""
    pts = []
    for seg in lines:
        p = str(seg).split()
        if len(p) < 3:
            continue
        t = p[0]
        price = _f(p[1])
        if price is None:
            continue
        time_s = (t[:2] + ":" + t[2:4]) if len(t) == 4 else t
        pts.append({"time": time_s, "price": price,
                    "volume": int(_f(p[2]) or 0),
                    "amount": float(p[3]) if len(p) > 3 and p[3] else 0})
    return pts

def _qt_meta(code, qt):
    """从腾讯 qt 报价数组补 name/price/preClose。qt[1]=名 qt[3]=现价 qt[4]=昨收"""
    name, price, pre = "", None, None
    if isinstance(qt, dict):
        q = qt.get(code)
        if isinstance(q, (list, tuple)) and len(q) > 4:
            name = str(q[1] or "")
            v = _f(q[3])
            if v is not None:
                price = v
            v = _f(q[4])
            if v is not None:
                pre = v
    return name, price, pre

def fetch_qq_min(code):
    qq = INDEX_QQ[code]

    def _fn(url):
        js = _get_json(url)
        if not isinstance(js, dict) or js.get("code") != 0:
            raise DeterministicReject("code!=0")
        cd = (js.get("data") or {}).get(qq)
        if not isinstance(cd, dict):
            raise DeterministicReject("no-code")
        inner = cd.get("data")
        lines = inner.get("data") if isinstance(inner, dict) else None
        if not isinstance(lines, list):
            raise DeterministicReject("no-lines")
        pts = _parse_qq_lines(lines)
        if not pts:
            raise DeterministicReject("empty-points")
        name, price, pre = _qt_meta(qq, cd.get("qt"))
        if price is None:
            price = pts[-1]["price"]
        date = _fmt_qq_date((inner.get("date") or cd.get("date") or ""))
        return {"name": name, "price": price, "preClose": pre, "date": date, "points": pts}

    return _host_loop(_qq_urls(qq, "min"), _fn)

def fetch_qq_day(code):
    qq = INDEX_QQ[code]

    def _fn(url):
        js = _get_json(url)
        if not isinstance(js, dict) or js.get("code") != 0:
            raise DeterministicReject("code!=0")
        cd = (js.get("data") or {}).get(qq)
        if not isinstance(cd, dict):
            raise DeterministicReject("no-code")
        recs = cd.get("data")
        lines, date, pre = None, None, None
        if isinstance(recs, list) and recs and isinstance(recs[0], dict):
            lines = recs[0].get("data")
            date = recs[0].get("date")
            pre = recs[0].get("prec")
        if not isinstance(lines, list):
            raise DeterministicReject("no-lines")
        pts = _parse_qq_lines(lines)
        if not pts:
            raise DeterministicReject("empty-points")
        name, price, pre2 = _qt_meta(qq, cd.get("qt"))
        if price is None:
            price = pts[-1]["price"]
        if pre is None and pre2 is not None:
            pre = pre2
        date = _fmt_qq_date(str(date) if date is not None else "")
        return {"name": name, "price": price, "preClose": pre, "date": date, "points": pts}

    return _host_loop(_qq_urls(qq, "day"), _fn)

_SINA_PRE_CLOSE_CACHE = {}          # sym -> {v, exp}
_SINA_PRE_CLOSE_LOCK = threading.Lock()

def _get_sina_pre_close(sym, last_date):
    """新浪昨收: scale=240 日线里选 day<last_date 的最新一根收盘(避免收盘后 scale=240 已含当日,
    把「当日收盘=当前价」误当昨收). 失败返回 None(不阻断整体, 前端会补快照昨收)"""
    key = (sym, last_date)
    with _SINA_PRE_CLOSE_LOCK:
        e = _SINA_PRE_CLOSE_CACHE.get(key)
        if e and e["exp"] > time.monotonic():
            return e["v"]
    if not BREAKERS["sina_day"].allow() or not BUCKETS["sina_day"].take(1):
        return None

    def _fn(url):
        js = _get_json(url)
        if not isinstance(js, list) or len(js) < 1:
            raise DeterministicReject("no-list")
        cand = None
        for bar in js:
            if not isinstance(bar, dict):
                continue
            day = str(bar.get("day") or "")[:10]
            if day and (last_date is None or day < last_date):
                cand = bar          # 升序, 最后一个满足条件的=最近前一交易日
        if cand is None:
            cand = js[-1]
        v = _f(cand.get("close"))
        if v is None:
            raise DeterministicReject("no-close")
        return v

    try:
        v = _host_loop(_sina_urls(sym, 240, 2), _fn)
        BREAKERS["sina_day"].record(True, True)
        with _SINA_PRE_CLOSE_LOCK:
            _SINA_PRE_CLOSE_CACHE[key] = {"v": v, "exp": time.monotonic() + PRE_CLOSE_TTL}
        return v
    except DeterministicReject:
        BREAKERS["sina_day"].record(False, True)
    except NetJitter:
        BREAKERS["sina_day"].record(False, False)
    return None

def fetch_sina(code):
    sym = INDEX_SINA.get(code)
    if not sym:
        raise DeterministicReject("no-sina-code")   # 港股不支持(实测 null), 当作确定性跳过

    def _fn(url):
        js = _get_json(url)
        if not isinstance(js, list) or not js:
            raise DeterministicReject("no-list")
        last_date = (js[-1].get("day") or "")[:10]
        pts = []
        for bar in js:
            day = bar.get("day") or ""
            if day[:10] != last_date:
                continue
            price = _f(bar.get("close"))
            if price is None:
                continue
            pts.append({"time": day[11:16], "price": price,
                        "volume": int(_f(bar.get("volume")) or 0),
                        "amount": float(bar.get("amount") or 0)})
        if not pts:
            raise DeterministicReject("empty-points")
        return {"name": "", "price": pts[-1]["price"], "preClose": None,
                "date": last_date, "points": pts, "_sym": sym}

    return _host_loop(_sina_urls(sym, 1, 241), _fn)

FETCHERS = {"em": fetch_em, "qq_min": fetch_qq_min, "sina": fetch_sina, "qq_day": fetch_qq_day}

# ------------------------------------------------------------------ 缓存 + in-flight 去重
class MiniCache:
    def __init__(self, ttl):
        self._m = {}
        self._ttl = ttl
        self._lk = threading.Lock()
        self.hits = 0
        self.misses = 0

    def fresh(self, key):
        with self._lk:
            e = self._m.get(key)
            if e and e["exp"] > time.monotonic():
                self.hits += 1
                return e["v"]
            if e:
                self.misses += 1
            return None

    def stale(self, key):
        with self._lk:
            e = self._m.get(key)
            return e["v"] if e else None

    def put(self, key, v):
        with self._lk:
            self._m[key] = {"v": v, "exp": time.monotonic() + self._ttl}
            if len(self._m) > _CACHE_MAX:
                # 清最旧一半(按 exp)
                for k in sorted(self._m, key=lambda k: self._m[k]["exp"])[: _CACHE_MAX // 2]:
                    self._m.pop(k, None)

    def size(self):
        with self._lk:
            return len(self._m)

CACHE = MiniCache(CACHE_TTL)

class InflightTable:
    """同 code 并发只放行一个真实上游(其余等结果), 与前端 _inflightMinute 同思路"""

    def __init__(self):
        self._m = {}
        self._lk = threading.Lock()

    def begin(self, key):
        with self._lk:
            e = self._m.get(key)
            if e is None:
                ev = threading.Event()
                box = {}
                e = (ev, box)
                self._m[key] = e
                return e, True
            return e, False

    def finish(self, key, ev, value):
        with self._lk:
            e = self._m.get(key)
            if e and e[0] is ev:
                e[1]["v"] = value
                e[0].set()

    def wait(self, e, timeout=2.0):
        e[0].wait(timeout)
        return e[1].get("v")

    def prune(self, key, ev):
        with self._lk:
            e = self._m.get(key)
            if e and e[0] is ev:
                del self._m[key]

INFLIGHT = InflightTable()

# ------------------------------------------------------------------ 主逻辑: 单个 code 的分源解析
def _resolve(code):
    """按优先级尝试(熔断跳过/限速跳过/失败换源), 返回 (payload, attempts, used_src, stale_from_last)"""
    attempts = []
    for src in SOURCE_ORDER:
        if src not in _RT_SOURCES or code not in _VALID_CODES.get(src, set()):
            attempts.append({"s": src, "skip": "n/a"})
            continue
        if not BREAKERS[src].allow():
            attempts.append({"s": src, "skip": "open"})
            continue
        if not BUCKETS[src].take(1):
            attempts.append({"s": src, "skip": "rate"})
            continue
        if src in _TEST_DET_FAIL:
            # 测试注入: 模拟该源确定性拒绝(业务/风控拒), 用于验证熔断
            BREAKERS[src].record(False, True)
            attempts.append({"s": src, "fail": "det:test-inject"})
            continue
        t0 = time.monotonic()
        try:
            data = FETCHERS[src](code)
            # 新浪补昨收(独立源 sina_day, 失败不影响整体)
            if src == "sina" and data["preClose"] is None and data.get("_sym"):
                data["preClose"] = _get_sina_pre_close(data["_sym"], data.get("date"))
            BREAKERS[src].record(True, True)
            data.pop("_sym", None)
            data["source"] = src
            data["points"] = sorted(data["points"], key=lambda p: p["time"])
            price, pre = data.get("price"), data.get("preClose")
            data["pct"] = ((price - pre) / pre * 100) if (price is not None and pre) else None
            return data, attempts + [{"s": src, "ok": True, "dur_ms": int((time.monotonic() - t0) * 1000)}], src
        except DeterministicReject as e:
            BREAKERS[src].record(False, True)
            attempts.append({"s": src, "fail": "det:%s" % e, "dur_ms": int((time.monotonic() - t0) * 1000)})
        except NetJitter as e:
            BREAKERS[src].record(False, False)
            attempts.append({"s": src, "fail": "net:%s" % e, "dur_ms": int((time.monotonic() - t0) * 1000)})
    return None, attempts, None

_VALID_CODES = {
    "em": set(INDEX_EM), "qq_min": set(INDEX_QQ), "qq_day": set(INDEX_QQ), "sina": set(INDEX_SINA),
}

_COUNTERS = {
    "intraday": 0, "cached": 0, "stale": 0, "miss": 0, "err": 0, "ratelimited": 0,
}
_COUNTERS_LOCK = threading.Lock()

def _bump(k):
    with _COUNTERS_LOCK:
        _COUNTERS[k] = _COUNTERS.get(k, 0) + 1

# ------------------------------------------------------------------ HTTP 服务
class _Handler(BaseHTTPRequestHandler):
    server_version = "rt_relay/1.0.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # 结构化日志走 _log

    # ---- CORS ----
    def _set_cors(self, send_origin=True):
        allow = _ALLOWED_ORIGINS
        origin = self.headers.get("Origin")
        if "*" in allow:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif send_origin and origin in allow:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors(send_origin=True)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, status, obj, cors=True):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._set_cors(cors)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- 路由 ----
    def _route(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            q = urllib.parse.parse_qs(parsed.query)
            if path == "/health":
                self._health()
            elif path == "/intraday":
                self._intraday(q)
            elif path in ("/", ""):
                self._send_json(200, {"service": "rt_relay", "ok": True,
                                      "usage": ["GET /intraday?code=bj50", "GET /health"]})
            else:
                self._send_json(404, {"error": "not found"})
        except BrokenPipeError:
            pass
        except Exception as e:
            _log({"evt": "http-exc", "path": self.path, "err": str(e)[:120]})
            try:
                self._send_json(500, {"error": "internal"})
            except Exception:
                pass

    def do_GET(self):
        self._route()

    # ---- /intraday ----
    def _intraday(self, q):
        _bump("intraday")
        code = (q.get("code") or [""])[0]
        if code not in INDEX_QQ:
            self._send_json(400, {"error": "unknown code", "code": code,
                                  "valid": sorted(INDEX_QQ)})
            return
        key = "intraday:" + code
        t0 = time.monotonic()

        # 1) 新鲜缓存直接喂
        fresh = CACHE.fresh(key)
        if fresh is not None:
            _bump("cached")
            _log({"evt": "intraday", "code": code, "status": 200, "cached": True,
                  "stale": False, "dur_ms": int((time.monotonic() - t0) * 1000)})
            out = dict(fresh)
            out["cached"] = True
            self._send_json(200, out)
            return

        # 2) in-flight 去重: 已有同 code 在抓则等其结果
        entry, owner = INFLIGHT.begin(key)
        if not owner:
            data = INFLIGHT.wait(entry, timeout=2.5)
            if data is not None:
                _bump("cached")
                self._send_json(200, data)
                return
            data = CACHE.stale(key)
            if data is not None:
                data2 = dict(data)
                data2["stale_try"] = True
                self._send_json(200, data2)
                return
            self._send_json(503, {"error": "upstream unavailable",
                                  "code": code, "tip": "try /health"})
            return

        # 3) owner: 在并发/全局限速护栏内解析
        with _CONC_SEM:
            _track_conc(1)
            try:
                if not GLOBAL_BUCKET.take(1):
                    _bump("ratelimited")
                    stale = CACHE.stale(key)
                    _log({"evt": "intraday-ratelimited", "code": code})
                    if stale is not None:
                        s = dict(stale)
                        s["stale"] = True
                        s["ratelimited"] = True
                        self._send_json(200, s)
                    else:
                        self._send_json(503, {"error": "global rate limited"})
                    return
                payload, attempts, used = _resolve(code)
            finally:
                _track_conc(-1)

        if payload is not None:
            payload["upstreams"] = attempts
            payload["cached"] = False
            payload["stale"] = False
            payload["ts"] = int(time.time() * 1000)
            CACHE.put(key, payload)
            INFLIGHT.finish(key, entry[0], payload)
            threading.Timer(4.0, lambda k=key, ev=entry[0]: INFLIGHT.prune(k, ev)).start()
            _log({"evt": "intraday", "code": code, "status": 200, "cached": False,
                  "stale": False, "src": used, "pts": len(payload.get("points", [])),
                  "upstreams": attempts, "dur_ms": int((time.monotonic() - t0) * 1000)})
            self._send_json(200, payload)
            return

        # 4) 全源失败 → 过期缓存兜底(stale) else 503
        stale = CACHE.stale(key)
        if stale is not None:
            _bump("stale")
            s = dict(stale)
            s["stale"] = True
            _log({"evt": "intraday", "code": code, "status": 200, "cached": False,
                  "stale": True, "upstreams": attempts, "dur_ms": int((time.monotonic() - t0) * 1000)})
            self._send_json(200, s)
            return
        _bump("miss")
        _log({"evt": "intraday", "code": code, "status": 503, "cached": False,
              "stale": False, "upstreams": attempts, "dur_ms": int((time.monotonic() - t0) * 1000)})
        INFLIGHT.finish(key, entry[0], None)
        threading.Timer(4.0, lambda k=key, ev=entry[0]: INFLIGHT.prune(k, ev)).start()
        self._send_json(503, {"error": "all sources failed", "code": code,
                              "upstreams": attempts, "tip": "try /health"})

    # ---- /health ----
    def _health(self):
        self._send_json(200, {
            "ok": True, "ts": int(time.time() * 1000), "uptime_s": int(time.monotonic() - _T0),
            "service": "rt_relay", "version": "1.0.0",
            "rate_windows_s": 60,
            "counters": dict(_COUNTERS),
            "cache": {"entries": CACHE.size(), "hits": CACHE.hits, "misses": CACHE.misses,
                      "ttl_s": CACHE_TTL},
            "sources": {n: dict(BREAKERS[n].info(), rate_per_min=RATE_LIMITS[n][0],
                                used_1min=BUCKETS[n].used_last_60s())
                        for n in sorted(RATE_LIMITS)},
            "global": {"used_1min": GLOBAL_BUCKET.used_last_60s(),
                       "limit_per_min": GLOBAL_LIMIT},
            "concurrency": {"current": _conc_now, "peak": _conc_peak,
                            "cap": max(1, CONCURRENCY)},
            "enabled_sources": sorted(_RT_SOURCES),
        })

def _track_conc(d):
    global _conc_now, _conc_peak
    with _conc_lock:
        _conc_now = max(0, _conc_now + d)
        if _conc_now > _conc_peak:
            _conc_peak = _conc_now

_T0 = time.monotonic()

def main():
    argv = sys.argv[1:]
    port = PORT
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    httpd = ThreadingHTTPServer((BIND, port), _Handler)
    httpd.daemon_threads = True
    _log({"evt": "start", "bind": "%s:%d" % (BIND, port), "sources": sorted(_RT_SOURCES),
          "origins": _ALLOWED_ORIGINS, "cache_ttl_s": CACHE_TTL, "concurrency_cap": CONCURRENCY,
          "rate_per_min": RATE_LIMITS, "test_det_fail": sorted(_TEST_DET_FAIL)})
    print("[rt_relay] listening on %s:%d (sources=%s)" % (BIND, port, sorted(_RT_SOURCES)),
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log({"evt": "stop"})

if __name__ == "__main__":
    main()