#!/usr/bin/env python3
"""
sensenova-rotate-proxy.py - 商汤 Sensenova 多 token 轮换本地代理(纯 key 轮换,不含任何 thinking 注入逻辑)

用途:商汤 token.sensenova.cn 对 deepseek-v4-flash 按 RPM(每分钟请求数)限流,单 token 撞 429
      (inference tpm exhausted)会反复导致 implementer 死限流;客户端退避间隔写死 4 秒封顶调不了。
      本代理在本地轮换 3 把 key,把 RPM 摊到 3 个池 = 变相 x3 吞吐。
      只做纯 key 轮换:监听本地端口 -> round-robin 选 key -> 转发 token.sensenova.cn(base=/)
      -> 上游 429 时换下一把 key 重试(轻退避)。与 thinking_proxy.py(思考注入)完全无关、完全独立。

用法(常驻,launchd 守护):
  bash scripts/sensenova-rotate-proxy.sh   # 包装脚本(负责从 .env 导出 key 再 exec 本代理)
  或直接(已注入 key 的 env):
  SENSENOVA_KEY1=.. SENSENOVA_KEY2=.. SENSENOVA_KEY3=.. \
  python3 scripts/sensenova-rotate-proxy.py
  监听 127.0.0.1:8899(可 TTP_PORT 改),转发 https://token.sensenova.cn/
  真实 key 禁进 git/日志;key 从 env 或 ../trade-data/.env(仓外)读 SENSENOVA_KEY1/2/3。

激活步骤:
  1. 确认 ../trade-data/.env 含 SENSENOVA_KEY1/2/3(本次已写入,仓外不提交)
  2. launchctl load scripts/com.trade.thinking-proxy.plist(TTP_PROVIDER=sensenova-rotate 守护本脚本)
  3. settings.json env "ANTHROPIC_BASE_URL": "http://127.0.0.1:8899"(切换由用户拍板,本次未动 settings)

风险(P0):代理挂 = 商汤轮换不可用。launchd KeepAlive 守护 + claude 重试兜底。
回退:bash scripts/thinking-proxy-rollback.sh sento(还原 settings 直连单 token 原状 + 停代理)。

env:
  SENSENOVA_KEY1/2/3        # 3 把商汤 key;缺 1 把则仅用已有 key 轮换(round-robin 长度=已有 key 数)
  SENSENOVA_ENV_FILE        # 回退读 .env 的路径,默认 /Users/linhuichen/code/trade-data/.env
  TTP_RETRY_ON_429=1        # 上游 429 时换下一把 key 重试(默认开)
  TTP_ROTATE_BACKOFF=0.3    # 429 换 key 重试的轻退避秒数(默认 0.3,避免把 3 池全打满)
  TTP_PORT=8899             # 监听端口(默认 8899,可改用于隔离测试实例)
"""
import http.server, http.client, threading, time, sys, ssl, os, json

UPSTREAM_HOST = "token.sensenova.cn"
UPSTREAM_PORT = 443
UPSTREAM_BASE = "/"
SSL_CTX = ssl._create_unverified_context()  # 本地代理,跳过证书验证(转发到已知 upstream)

LOG = os.environ.get("TTP_LOG", "/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log")

# ═══ 3 把 key 加载(真实 key 禁进 git/日志)═══
# 读取顺序:先看 env(SENSENOVA_KEY1/2/3),再回退读 ../trade-data/.env(仓外)。
# 缺 key 的:只加入有值 key 轮换;一把都没有 = 不启用轮换(回到单 key 直发,失败透明)。
def _load_keys():
    keys = []
    for _k in ("SENSENOVA_KEY1", "SENSENOVA_KEY2", "SENSENOVA_KEY3"):
        _v = os.environ.get(_k, "").strip()
        if _v:
            keys.append(_v)
    if keys:
        return keys
    _env_file = os.environ.get("SENSENOVA_ENV_FILE", "/Users/linhuichen/code/trade-data/.env")
    try:
        with open(_env_file) as _f:
            _m = {}
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _kk, _vv = _line.split("=", 1)
                _m[_kk.strip()] = _vv.strip().strip('"').strip("'")
            for _k in ("SENSENOVA_KEY1", "SENSENOVA_KEY2", "SENSENOVA_KEY3"):
                _v = _m.get(_k, "").strip()
                if _v:
                    keys.append(_v)
    except FileNotFoundError:
        pass
    except Exception as e:
        logmsg(f"WARN sensenova .env read failed: {e}")
    return keys

KEYS = _load_keys()
RETRY_ON_429 = os.environ.get("TTP_RETRY_ON_429", "1") == "1"
ROTATE_BACKOFF = float(os.environ.get("TTP_ROTATE_BACKOFF", "0.3"))
_rotate_idx = 0
_rotate_lock = threading.Lock()

def logmsg(s):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {s}\n")
    except Exception:
        pass
    print(s, flush=True)

def _do_upstream(command, upstream_path, body, headers, auth_key):
    """单次 upstream 请求。auth_key=None 沿用客户端原样头;否则覆写 Authorization: Bearer <key>。
    返回 (status, resp_body, resp_headers, resp_text, upstream_err)。"""
    conn = http.client.HTTPSConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=180, context=SSL_CTX)
    h = {k: v for k, v in headers.items() if k.lower() not in ("host", "content-length", "connection")}
    h["Host"] = UPSTREAM_HOST
    if auth_key is not None:
        h["Authorization"] = "Bearer " + auth_key
    try:
        conn.request(command, upstream_path, body=body, headers=h)
        resp = conn.getresponse()
        resp_body = resp.read()
        resp_headers = resp.getheaders()
        resp_text = resp_body.decode("utf-8", "replace")
        conn.close()
        return resp.status, resp_body, resp_headers, resp_text, None
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return None, None, None, None, str(e)

# ═══ thinking_budget 剥离(A 方案,2026-09-01)═══
# 商汤 deepseek-v4-flash 端点不支持 thinking_budget 参数,Claude Code 对 deepseek
# 模型自动注入该参数(新会话重做 model capability 判定识别为 reasoning 模型)致 400。
# 纯转发代理在转发前剥掉该字段。glm 系列不发该参数,剥离无害。
def _strip_thinking_budget(body, content_type, path):
    """剥掉请求体里的 thinking_budget 字段。
    返回 (new_body_bytes, stripped: bool)。仅当 content_type 含 json 且 body 非空
    且解析为 dict 且含 thinking_budget 键时才剥;解析失败/非 dict/无该键原样返回不破坏。"""
    if not body or "json" not in (content_type or "").lower():
        return body, False
    try:
        data = json.loads(body)
    except Exception:
        return body, False  # 解析失败:原样返回,不破坏上游
    if not isinstance(data, dict) or "thinking_budget" not in data:
        return body, False
    del data["thinking_budget"]
    logmsg(f"STRIP thinking_budget {path}")
    new_body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return new_body, True

# ═══ 结构化请求检测日志(确认 thinking_budget 添加契机根因,2026-09-01)═══
# TTP_DETECT_LOG=1 才开(默认关,量控第一道)。记录每次请求元数据(带/不带
# thinking_budget 都记,has_tb 字段区分),对比找出 thinking_budget 什么契机被注入。
# 全局计数上限 50000 条(约 7.5MB),达到后停记并 logmsg 一次 "DETECT capped at 50000"。
# 用 logmsg 写(复用 sensenova-rotate-req.log,不自建文件)。
_DETECT_COUNT = 0

def _detect_log(command, path, body, content_type):
    """记录请求元数据一行,对比 thinking_budget 何时出现。
    仅当 TTP_DETECT_LOG=1 且 body 非空且 content_type 含 json 才记;解析失败记 parse_fail;
    非 dict / 非不记。不带 thinking_budget 的请求也记(has_tb=F),这是对比找契机的关键。"""
    global _DETECT_COUNT
    if os.environ.get("TTP_DETECT_LOG") != "1":
        return
    if _DETECT_COUNT >= 50000:
        if _DETECT_COUNT == 50000:
            logmsg("DETECT capped at 50000")
            _DETECT_COUNT += 1  # 仅记一次封顶提示,后续静默 return
        return
    if not body or "json" not in (content_type or "").lower():
        return
    try:
        data = json.loads(body)
    except Exception:
        logmsg(f"DETECT {command} {path} parse_fail")
        _DETECT_COUNT += 1
        return
    if not isinstance(data, dict):
        return
    model = data.get("model", "-")
    has_tb = "thinking_budget" in data
    tb_val = data.get("thinking_budget", "-")
    nmsg = len(data.get("messages", []))
    has_sys = "T" if data.get("system") else "F"
    ntools = len(data.get("tools", []))
    logmsg(f"DETECT {command} {path} model={model} has_tb={'T' if has_tb else 'F'} tb_val={tb_val} nmsg={nmsg} has_sys={has_sys} ntools={ntools}")
    _DETECT_COUNT += 1

class Handler(http.server.BaseHTTPRequestHandler):
    def _forward(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        upstream_path = UPSTREAM_BASE + self.path
        # 可选 body dump(溯源用):TTP_DUMP_BODY=1 时落原始 body(剥离前),抓真实请求体看 thinking_budget 何时出现
        if os.environ.get("TTP_DUMP_BODY") == "1" and body:
            try:
                logmsg(f"REQBODY {self.path} {body[:500]}")
            except Exception:
                pass
        # 结构化检测日志(TTP_DETECT_LOG=1 开):记录请求元数据(剥离前原始 body),对比 thinking_budget 添加契机
        _detect_log(self.command, self.path, body, self.headers.get("Content-Type", ""))
        # 转发前剥掉 thinking_budget(商汤 deepseek-v4-flash 不支持该参数)
        body, _stripped = _strip_thinking_budget(body, self.headers.get("Content-Type", ""), self.path)
        # 尝试序列:轮换开启且有 key -> 从 round-robin 游标起的多把 key;否则 -> [None](不覆写头)
        try_keys = [None]
        if KEYS:
            global _rotate_idx
            with _rotate_lock:
                start = _rotate_idx
                _rotate_idx = (_rotate_idx + 1) % len(KEYS)
            try_keys = [KEYS[(start + i) % len(KEYS)] for i in range(len(KEYS))]
        last = None
        for k, key in enumerate(try_keys):
            if k > 0 and ROTATE_BACKOFF > 0:
                time.sleep(ROTATE_BACKOFF)  # 换 key 重试前轻退避,避免把 3 池全打满
            status, resp_body, resp_headers, resp_text, err = _do_upstream(
                self.command, upstream_path, body, self.headers, key)
            if err is not None:
                logmsg(f"UPSTREAM ERR {err}")
                self.send_response(502); self.end_headers(); self.wfile.write(str(err).encode()); return
            last = (status, resp_body, resp_headers, resp_text)
            # 429 = 该 key 的 RPM/tpm 池耗尽 -> 换下一把 key 重试(仅未到尝试序列末尾)
            if status == 429 and k < len(try_keys) - 1 and RETRY_ON_429:
                logmsg(f"429 detected, rotate to next key (try {k+2}/{len(try_keys)})")
                continue
            break
        status, resp_body, resp_headers, resp_text = last
        logmsg(f"RESP {self.command} {self.path} -> {status} bytes={len(resp_body)}")
        self.send_response(status)
        for kk, vv in resp_headers:
            if kk.lower() in ("transfer-encoding", "connection", "content-length"):
                continue
            self.send_header(kk, vv)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)
    def do_POST(self): self._forward()
    def do_GET(self): self._forward()
    def do_PUT(self): self._forward()
    def do_DELETE(self): self._forward()
    def do_OPTIONS(self): self._forward()
    def log_message(self, *a): pass

if __name__ == "__main__":
    _port = int(os.environ.get("TTP_PORT", "8899"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", _port), Handler)
    logmsg(f"sensenova-rotate-proxy listening on 127.0.0.1:{_port} -> https://{UPSTREAM_HOST}{UPSTREAM_BASE} "
           f"rotate_keys={len(KEYS)} retry429={RETRY_ON_429} backoff={ROTATE_BACKOFF}")
    server.serve_forever()
