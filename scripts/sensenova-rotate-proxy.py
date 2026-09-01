#!/usr/bin/env python3
"""
sensenova-rotate-proxy.py - 商汤 Sensenova 多 token 轮换本地代理(纯 key 轮换,不含任何 thinking 注入逻辑)

用途:商汤 token.sensenova.cn 对 deepseek-v4-flash 按 RPM(每分钟请求数)限流,单 token 撞 429
      (inference tpm exhausted)会反复导致 implementer 死限流;客户端退避间隔写死 4 秒封顶调不了。
      本代理在本地轮换 4 把 key,把 RPM 摊到 4 个池 = 变相 x4 吞吐。
      只做纯 key 轮换:监听本地端口 -> round-robin 选 key -> 转发 token.sensenova.cn(base=/)
      -> 上游 429 时换下一把 key 重试(轻退避)。与 thinking_proxy.py(思考注入)完全无关、完全独立。

用法(常驻,launchd 守护):
  bash scripts/sensenova-rotate-proxy.sh   # 包装脚本(负责从 .env 导出 key 再 exec 本代理)
  或直接(已注入 key 的 env):
  SENSENOVA_KEY1=.. SENSENOVA_KEY2=.. SENSENOVA_KEY3=.. SENSENOVA_KEY4=.. \
  python3 scripts/sensenova-rotate-proxy.py
  监听 127.0.0.1:8899(可 TTP_PORT 改),转发 https://token.sensenova.cn/
  真实 key 禁进 git/日志;key 从 env 或 ../trade-data/.env(仓外)读 SENSENOVA_KEY1/2/3/4。

激活步骤:
  1. 确认 ../trade-data/.env 含 SENSENOVA_KEY1/2/3/4(本次已写入,仓外不提交)
  2. launchctl load scripts/com.trade.thinking-proxy.plist(TTP_PROVIDER=sensenova-rotate 守护本脚本)
  3. settings.json env "ANTHROPIC_BASE_URL": "http://127.0.0.1:8899"(切换由用户拍板,本次未动 settings)

风险(P0):代理挂 = 商汤轮换不可用。launchd KeepAlive 守护 + claude 重试兜底。
回退:bash scripts/thinking-proxy-rollback.sh sento(还原 settings 直连单 token 原状 + 停代理)。

env:
  SENSENOVA_KEY1/2/3/4        # 4 把商汤 key;缺 1 把则仅用已有 key 轮换(round-robin 长度=已有 key 数)
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

# ═══ 4 把 key 加载(真实 key 禁进 git/日志)═══
# 读取顺序:先看 env(SENSENOVA_KEY1/2/3/4),再回退读 ../trade-data/.env(仓外)。
# 缺 key 的:只加入有值 key 轮换;一把都没有 = 不启用轮换(回到单 key 直发,失败透明)。
# 返回 (keys, key_nums):key_nums 与 keys 并行,记录每把 key 的序号(1/2/3/4),用于冷却日志标识。
def _load_keys():
    keys, nums = [], []
    for _i, _k in enumerate(("SENSENOVA_KEY1", "SENSENOVA_KEY2", "SENSENOVA_KEY3", "SENSENOVA_KEY4"), start=1):
        _v = os.environ.get(_k, "").strip()
        if _v:
            keys.append(_v)
            nums.append(_i)
    if keys:
        return keys, nums
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
            for _i, _k in enumerate(("SENSENOVA_KEY1", "SENSENOVA_KEY2", "SENSENOVA_KEY3", "SENSENOVA_KEY4"), start=1):
                _v = _m.get(_k, "").strip()
                if _v:
                    keys.append(_v)
                    nums.append(_i)
    except FileNotFoundError:
        pass
    except Exception as e:
        logmsg(f"WARN sensenova .env read failed: {e}")
    return keys, nums

KEYS, KEY_NUMS = _load_keys()
RETRY_ON_429 = os.environ.get("TTP_RETRY_ON_429", "1") == "1"
ROTATE_BACKOFF = float(os.environ.get("TTP_ROTATE_BACKOFF", "0.3"))
_rotate_idx = 0
_rotate_lock = threading.Lock()

# ═══ 单 key 分层冷却(429 额度型限流,2026-09-01 用户定)═══
# 商汤 429 分两类:短时限流(inference tpm / rpm exhausted)靠换 key 重试即解,不冷却;
# 账户额度型(token plan entitlement / Allocated quota)5h 刷新,换 key 无用 → 单 key 进入较长冷却,
# 轮换跳过它,其他 key 正常(4 把 key = 4 个独立账号额度,按 key 隔离不整池)。
# 冷却序列(先探后拉长):level 0 → 30min;level>=1 → 1h;最多 5 次 1h 封顶(累计 5.5h>=5h 刷新周期)。
# 冷却结束再触发 → 重置回 30min:key 在冷却后若成功过(非429响应)则清冷却,新触发即 fresh level=0。
COOL_L0_SEC = 30 * 60        # level 0 冷却 30 分钟
COOL_LN_SEC = 60 * 60        # level>=1 冷却 1 小时
COOL_MAX_LEVEL = 5           # level 封顶(最多 5 次 1h)
_cool = {}                   # key -> {"until": epoch, "level": int}(内存,不落盘)
_cool_lock = threading.Lock()

def _cool_duration_sec(level):
    """按退避档位返回冷却秒数:level 0=30min,level>=1=1h。"""
    return COOL_L0_SEC if level <= 0 else COOL_LN_SEC

def _parse_429_msg(resp_text):
    """从 429 响应 JSON 解析 error.message,区分短时限流 vs 账户额度型。
    返回 (category, msg),category in {"short","quota","unknown"};unknown 按 short 处理(继续轮换)。"""
    msg = ""
    try:
        _data = json.loads(resp_text or "")
        if isinstance(_data, dict):
            _err = _data.get("error")
            if isinstance(_err, dict):
                msg = _err.get("message", "") or ""
            elif isinstance(_err, str):
                msg = _err
    except Exception:
        msg = ""
    _low = (msg or "").lower()
    if "tpm exhausted" in _low or "rpm exhausted" in _low:
        return "short", msg
    if "token plan entitlement" in _low or "allocated quota" in _low:
        return "quota", msg
    return "unknown", msg

def _mark_cool(key, key_num, msg):
    """额度型 429 → 标记单 key 冷却。entry 存在(上次冷却未成功即再触发)= escalation level+1;
    无 entry(首次/冷却后成功过)= fresh level 0(重置回 30min)。封顶 COOL_MAX_LEVEL。"""
    with _cool_lock:
        _entry = _cool.get(key)
        if _entry:
            _level = min(_entry["level"] + 1, COOL_MAX_LEVEL)
        else:
            _level = 0
        _until = time.time() + _cool_duration_sec(_level)
        _cool[key] = {"until": _until, "level": _level}
    _dur = "30min" if _level == 0 else f"{_level}h"
    logmsg(f"COOL KEY{key_num} until {time.strftime('%H:%M', time.localtime(_until))} msg={msg} level={_level} ({_dur})")

def _unmark_cool(key):
    """成功响应(非429/400)后清除该 key 冷却,使下次额度型 429 重新从 30min 探(重置)。"""
    with _cool_lock:
        _cool.pop(key, None)

def _cooled_out(key):
    """该 key 是否处于冷却期(now < until)。"""
    with _cool_lock:
        _e = _cool.get(key)
        if not _e:
            return False
        return time.time() < _e["until"]

# 日志大小上限:超过即裁剪只留尾部(保留最近日志,防无限膨胀;2026-09-01 用户定
# "文件别太大,问题出现时最近的错误日志就够")。LOG_MAX_BYTES=20MB,裁剪留尾 10MB。
LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_KEEP_TAIL_BYTES = 10 * 1024 * 1024

def logmsg(s):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        # 大小守卫:超上限则留尾截断(只读尾段写回,保留最近错误日志)
        try:
            if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX_BYTES:
                with open(LOG, "rb") as f:
                    f.seek(-LOG_KEEP_TAIL_BYTES, os.SEEK_END)
                    tail = f.read()
                with open(LOG, "wb") as f:
                    f.write(tail)
        except Exception:
            pass
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

# ═══ thinking_budget 注入(绕过商汤推导超限,2026-09-01)═══
# 商汤 deepseek-v4-flash 端点偶发对大上下文请求报
# "thinking_budget parameter must be a positive integer and not greater than 393216"
# 但 body 本无该参数(has_tb=F)= 商汤自己推导,推导偶发超上限报 400(概率性,同请求第一次200第二次400)。
# 代理主动注入合法值 32768(远小于 393216 上限,32K token thinking 够用),
# 让商汤拿到现成合法值跳过自己推导。从严条件避免误伤 glm/不带 thinking 的请求。
INJECT_TB_VALUE = 32768

def _inject_thinking_budget(body, content_type, path, req_headers):
    """注入合法 thinking_budget,绕过商汤自己推导超限的 bug。
    返回 (new_body_bytes, injected: bool)。从严条件:
    ① content_type 含 json ② body 解析为 dict ③ model 含 deepseek(只 deepseek)
    ④ body 未显式带 thinking_budget(不覆盖客户端已有)
    ⑤ 请求 anthropic-beta header 含 interleaved-thinking 或 thinking-token-count(带 thinking flags)
    json.loads 失败/非 dict -> 原样返回不破坏。"""
    if not body or "json" not in (content_type or "").lower():
        return body, False
    try:
        data = json.loads(body)
    except Exception:
        return body, False
    if not isinstance(data, dict):
        return body, False
    model = data.get("model", "") or ""
    if "deepseek" not in model.lower():
        return body, False
    if "thinking_budget" in data:
        return body, False  # 客户端已显式带,不覆盖
    beta = req_headers.get("anthropic-beta", "") or ""
    if "interleaved-thinking" not in beta and "thinking-token-count" not in beta:
        return body, False  # 不带 thinking flags 不注入
    data["thinking_budget"] = INJECT_TB_VALUE
    logmsg(f"INJECT thinking_budget={INJECT_TB_VALUE} {path}")
    # 归一化嵌套 thinking 字段:商汤 deepseek-v4-flash 要求 thinking.budget_tokens <= 1024。
    # Claude Code 新版发 {thinking:{type:adaptive,budget_tokens:大值}} -> 商汤 400
    # (BudgetTokens invalid / type adaptive invalid,同根因,校验路径不同)。压到 1024 绕过。
    # (2026-09-01 实测:budget<=1024 时 adaptive/enabled 均 200;顶层 thinking_budget 已另注入处理预算)
    _tn = data.get("thinking")
    if isinstance(_tn, dict):
        _bt = _tn.get("budget_tokens")
        if isinstance(_bt, (int, float)) and _bt > 1024:
            _tn["budget_tokens"] = 1024
            logmsg(f"CLAMP thinking.budget_tokens {_bt}->1024 {path}")
    new_body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return new_body, True

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
        # 结构化检测日志(TTP_DETECT_LOG=1 开):记录请求元数据(原始 body),对比 thinking_budget 添加契机
        _detect_log(self.command, self.path, body, self.headers.get("Content-Type", ""))
        # 转发前注入合法 thinking_budget(绕过商汤自己推导超限的 400 bug,只对带 thinking flags 的 deepseek 请求)
        body, _injected = _inject_thinking_budget(body, self.headers.get("Content-Type", ""), self.path, self.headers)
        # 尝试序列:轮换开启且有 key -> 从 round-robin 游标起取所有「非冷却」key(跳过冷却中的 key);
        # 否则 -> [None](不覆写头)。try_keys 为 (key, key_num) 元组,key_num 用于冷却日志。
        try_keys = [(None, 0)]
        if KEYS:
            global _rotate_idx
            with _rotate_lock:
                start = _rotate_idx
                _rotate_idx = (_rotate_idx + 1) % len(KEYS)
            _rot = []
            for _i in range(len(KEYS)):
                _ki = (start + _i) % len(KEYS)
                _key = KEYS[_ki]
                if _cooled_out(_key):
                    logmsg(f"SKIP COOLED KEY{KEY_NUMS[_ki]} (until {time.strftime('%H:%M', time.localtime(_cool.get(_key, {}).get('until', 0)))})")
                    continue
                _rot.append((_key, KEY_NUMS[_ki]))
            if _rot:
                try_keys = _rot
            else:
                # 全部 key 冷却中(极端):不静默,如实返回 429 给客户端
                logmsg("ALL KEYS COOLED, return 429")
                _b = b'{"type":"error","error":{"type":"rate_limit_error","message":"all keys cooling (quota exhausted)"}}'
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(_b)))
                self.end_headers()
                self.wfile.write(_b)
                return
        last = None
        for k, (key, key_num) in enumerate(try_keys):
            if k > 0 and ROTATE_BACKOFF > 0:
                time.sleep(ROTATE_BACKOFF)  # 换 key 重试前轻退避,避免把 3 池全打满
            status, resp_body, resp_headers, resp_text, err = _do_upstream(
                self.command, upstream_path, body, self.headers, key)
            if err is not None:
                logmsg(f"UPSTREAM ERR {err}")
                self.send_response(502); self.end_headers(); self.wfile.write(str(err).encode()); return
            last = (status, resp_body, resp_headers, resp_text)
            # 成功/非限流响应 -> 清除该 key 冷却(额度恢复,下次额度型 429 重新从 30min 探)
            if key is not None and status not in (429, 400):
                _unmark_cool(key)
            if k < len(try_keys) - 1 and RETRY_ON_429:
                if status == 429:
                    # 分层:短时限流(tpm/rpm)继续轮换;额度型(token plan/allocated quota)单 key 冷却后继续轮换
                    _cat, _msg = _parse_429_msg(resp_text)
                    if _cat == "quota" and key is not None:
                        _mark_cool(key, key_num, _msg)
                    logmsg(f"429 detected, rotate to next key (try {k+2}/{len(try_keys)})")
                    continue
                if status == 400 and "thinking_budget" in (resp_text or ""):
                    logmsg(f"400 thinking_budget detected, rotate to next key (try {k+2}/{len(try_keys)})")
                    continue
            break
        status, resp_body, resp_headers, resp_text = last
        logmsg(f"RESP {self.command} {self.path} -> {status} bytes={len(resp_body)}")
        # 诊断:4xx 时落响应错误正文 + 请求 header(TTP_DUMP_BODY=1 且 status>=400),定位商汤拒绝的根因
        if status >= 400 and os.environ.get("TTP_DUMP_BODY") == "1" and resp_text:
            logmsg(f"RESPERR {self.path} -> {status} body={resp_text[:800]}")
            # 抓请求 header(怀疑 thinking_budget 走 header 传到商汤,不在 body)
            try:
                logmsg(f"RESPERR {self.path} -> {status} reqheaders={ {k: (v[:120] if 'auth' not in k.lower() and 'token' not in k.lower() and 'key' not in k.lower() else '***') for k, v in self.headers.items()} }")
            except Exception:
                pass
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
