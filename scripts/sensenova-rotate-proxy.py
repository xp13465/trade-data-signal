#!/usr/bin/env python3
"""
sensenova-rotate-proxy.py - 商汤 Sensenova 多 token 轮换本地代理(纯 key 轮换,不含任何 thinking 注入逻辑)

用途:商汤 token.sensenova.cn 对 deepseek-v4-flash 按 RPM(每分钟请求数)限流,单 token 撞 429
      (inference tpm exhausted)会反复导致 implementer 死限流;客户端退避间隔写死 4 秒封顶调不了。
      本代理在本地轮换 5 把 key,把 RPM 摊到 5 个池 = 变相 x5 吞吐。
      只做纯 key 轮换:监听本地端口 -> round-robin 选 key -> 转发 token.sensenova.cn(base=/)
      -> 上游 429 时换下一把 key 重试(轻退避)。与 thinking_proxy.py(思考注入)完全无关、完全独立。

用法(常驻,launchd 守护):
  bash scripts/sensenova-rotate-proxy.sh   # 包装脚本(负责从 .env 导出 key 再 exec 本代理)
  或直接(已注入 key 的 env):
  SENSENOVA_KEY1=.. SENSENOVA_KEY2=.. SENSENOVA_KEY3=.. SENSENOVA_KEY4=.. SENSENOVA_KEY5=.. \
  python3 scripts/sensenova-rotate-proxy.py
  监听 127.0.0.1:8899(可 TTP_PORT 改),转发 https://token.sensenova.cn/
  真实 key 禁进 git/日志;key 从 env 或 ../trade-data/.env(仓外)读 SENSENOVA_KEY1/2/3/4/5。

激活步骤:
  1. 确认 ../trade-data/.env 含 SENSENOVA_KEY1/2/3/4/5(本次已写入,仓外不提交)
  2. launchctl load scripts/com.trade.thinking-proxy.plist(TTP_PROVIDER=sensenova-rotate 守护本脚本)
  3. settings.json env "ANTHROPIC_BASE_URL": "http://127.0.0.1:8899"(切换由用户拍板,本次未动 settings)

风险(P0):代理挂 = 商汤轮换不可用。launchd KeepAlive 守护 + claude 重试兜底。
回退:bash scripts/thinking-proxy-rollback.sh sento(还原 settings 直连单 token 原状 + 停代理)。

env:
  SENSENOVA_KEY1/2/3/4/5      # 5 把商汤 key;缺 1 把则仅用已有 key 轮换(round-robin 长度=已有 key 数)
  SENSENOVA_ENV_FILE        # 回退读 .env 的路径,默认 /Users/linhuichen/code/trade-data/.env
  TTP_RETRY_ON_429=1        # 上游 429 时换下一把 key 重试(默认开)
  TTP_ROTATE_BACKOFF=0.3    # 429 换 key 重试的轻退避秒数(默认 0.3,避免把 3 池全打满)
  TTP_PORT=8899             # 监听端口(默认 8899,可改用于隔离测试实例)
  TTP_REQDUMP=1             # 请求原文滚动 dump(默认开,TTP_REQDUMP=0 关);只落 body 不落 header
  TTP_REQDUMP_DIR=.../sensenova-req-dump  # dump 目录(默认 trade-data/data/logs/sensenova-req-dump,仓外)
  TTP_REQDUMP_KEEP=30       # 非 ERR 保留最近 N 个(默认 30)
  TTP_REQDUMP_KEEP_ERR=30   # ERR(>=400)保留最近 N 个(默认 30,报错原文不滚删)
"""
import http.server, http.client, threading, time, sys, ssl, os, json

UPSTREAM_HOST = "token.sensenova.cn"
UPSTREAM_PORT = 443
UPSTREAM_BASE = "/"
SSL_CTX = ssl._create_unverified_context()  # 本地代理,跳过证书验证(转发到已知 upstream)

LOG = os.environ.get("TTP_LOG", "/Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log")

# ═══ 5 把 key 加载(真实 key 禁进 git/日志)═══
# 读取顺序:先看 env(SENSENOVA_KEY1/2/3/4/5),再回退读 ../trade-data/.env(仓外)。
# 缺 key 的:只加入有值 key 轮换;一把都没有 = 不启用轮换(回到单 key 直发,失败透明)。
# 返回 (keys, key_nums):key_nums 与 keys 并行,记录每把 key 的序号(1/2/3/4/5),用于冷却日志标识。
def _load_keys():
    keys, nums = [], []
    for _i, _k in enumerate(("SENSENOVA_KEY1", "SENSENOVA_KEY2", "SENSENOVA_KEY3", "SENSENOVA_KEY4", "SENSENOVA_KEY5"), start=1):
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
            for _i, _k in enumerate(("SENSENOVA_KEY1", "SENSENOVA_KEY2", "SENSENOVA_KEY3", "SENSENOVA_KEY4", "SENSENOVA_KEY5"), start=1):
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

# ═══ 9-14 高峰主动限频(2026-09-01 用户拍板,B方案②)═══
# 北京时间 9:00-14:00 为 quota 型 429 高峰(日志实测延伸至 16:00,诚实标注见
# docs/sensenova/sensenova-cooling-recovery-distribution.md;默认窗口按用户拍板写死 9-14)。
# 高峰行为:①该 key 冷却时长 ×PEAK_COOL_MULT(翻倍,高峰恢复更慢,减少空转)
#          ②429 换 key 退避提升至 PEAK_ROTATE_BACKOFF(降低高峰换 key 重试请求率)
# 非高峰行为完全不变。窗口可用 TTP_PEAK_HOURS 覆盖(默认 "9-14",如想扩至 9-16 改 env 即可)。
# ⚠️ 高峰按北京时间,节假日可能误判是已知边界。
PEAK_HOURS = os.environ.get("TTP_PEAK_HOURS", "9-14")
PEAK_START_HOUR, PEAK_END_HOUR = (int(x) for x in PEAK_HOURS.split("-"))
PEAK_COOL_MULT = 2.0        # 高峰 quota 冷却时长倍率
PEAK_ROTATE_BACKOFF = 1.5   # 高峰 429 换 key 退避秒数(非高峰 0.3,见 ROTATE_BACKOFF)

def _is_peak_hour():
    """北京时间高峰窗口判定:[PEAK_START, PEAK_END) 含头不含尾(默认 9<=h<14 即 9/10/11/12/13 点)。"""
    _h = time.localtime().tm_hour
    return PEAK_START_HOUR <= _h < PEAK_END_HOUR

def _rotate_backoff():
    """429 换 key 重试退避秒数:高峰 1.5s(下限),非高峰 0.3s(env 可改更大)。"""
    if _is_peak_hour():
        return max(ROTATE_BACKOFF, PEAK_ROTATE_BACKOFF)
    return ROTATE_BACKOFF

# ═══ 单 key 分层冷却(429 额度型限流,2026-09-01 用户定)═══
# 商汤 429 分两类:短时限流(inference tpm / rpm exhausted)靠换 key 重试即解,不冷却;
# 账户额度型(token plan entitlement / Allocated quota)刷新,换 key 无用 → 单 key 冷却,
# 轮换跳过它,其他 key 正常(5 把 key = 5 个独立账号额度,按 key 隔离不整池)。
# 冷却序列(先探后拉长,2026-09-01 数据定档,依据 docs/sensenova/sensenova-cooling-recovery-distribution.md):
#   level0=180s(3min)起步,每级 ×2(180/360/720/1440/2880s)封顶 48min。
#   定档数据:60s 起步冷却下,解除后 p50 仅 48s 又撞 quota 429(36% 场景 <30s 又撞)= 空转实锤;
#   3min 起步越过「假恢复快速又撞」区(p50=48s),解除时点配额恢复更充分,单次可用期拉长;
#   封顶 48min 覆盖冷却占用 p99(39.9min)的极端恢复场景。真死 key 靠递增退避自然隔离,不会狂试。
#   冷却结束再触发 → 重置回 level0:key 在冷却后若成功过(非429响应)则清冷却,新触发即 fresh level=0。
COOL_L0_SEC = 180          # level 0 冷却 180 秒(3min)起步(数据定档,替代旧 60s)
COOL_MAX_LEVEL = 5         # level 封顶(180/360/720/1440/2880s 五档,真死 key 递增隔离)
_cool = {}                 # key -> {"until": epoch, "level": int}(内存,不落盘)
_cool_lock = threading.Lock()

def _cool_duration_sec(level):
    """递增退避:level0=180s,level1=360s,...,封顶 2880s(48min)。
    定档依据:日志 60s 冷却下解除后 p50 仅 48s 又撞 quota 429(36% <30s)= 空转;
    3min 起步越过假恢复区,封顶 48min 覆盖冷却占用 p99(39.9min)。
    恢复快的 key 3 分钟内复役,真死 key 递增拉长。"""
    return min(COOL_L0_SEC * (2 ** min(level, COOL_MAX_LEVEL - 1)), 48 * 60)

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
    无 entry(首次/冷却后成功过)= fresh level 0(重置回 180s)。封顶 COOL_MAX_LEVEL。
    高峰窗口内冷却时长 ×PEAK_COOL_MULT(翻倍),减少高峰空转(9-14 高峰,见 _is_peak_hour)。"""
    with _cool_lock:
        _entry = _cool.get(key)
        if _entry:
            _level = min(_entry["level"] + 1, COOL_MAX_LEVEL)
        else:
            _level = 0
        _dur = _cool_duration_sec(_level)
        if _is_peak_hour():
            _dur = int(_dur * PEAK_COOL_MULT)
        _until = time.time() + _dur
        _cool[key] = {"until": _until, "level": _level}
    _dur_min = f"{_dur//60}min"
    logmsg(f"COOL KEY{key_num} until {time.strftime('%H:%M', time.localtime(_until))} msg={msg} level={_level} ({_dur_min})")

def _unmark_cool(key):
    """成功响应(非429/400)后清除该 key 冷却,使下次额度型 429 重新从 180s 探(重置)。"""
    with _cool_lock:
        _cool.pop(key, None)

def _cooled_out(key):
    """该 key 是否处于冷却期(now < until)。"""
    with _cool_lock:
        _e = _cool.get(key)
        if not _e:
            return False
        return time.time() < _e["until"]

# ═══ 全 key 冷却时保守整体退避(2026-09-01 用户拍板,B方案③保守版)═══
# 全部 key 冷却中 → 不直接返回 429,进入递增退避等待(30s 起步 ×2,单次封顶 8min),
# 退避期间不发请求(不把 key 打进长冷却),到点重新探测是否有 key 恢复可复用;
# 累计等待超 ALL_COOL_BACKOFF_CAP(8min)仍全冷却 → 如实返回 429。
# ⚠️ 明确:这是保守等待重试版,不做「容量超载」判定——响应特征分不清容量 vs 配额,
#     避免误判,只做等待重试(非容量判定逻辑)。
ALL_COOL_BACKOFF_L0 = 30      # 全冷却整体退避 30s 起步
ALL_COOL_BACKOFF_MAX = 480    # 单次退避封顶 480s(8min)
ALL_COOL_BACKOFF_CAP = 480    # 累计等待上限 480s(8min),超限仍全冷却 → 返回 429

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

# ═══ 请求原文滚动 dump(2026-09-01 用户定,纯诊断增强)═══
# 目的:保留最近 N 次请求原文(转发后字节,逐字节原样),报错(>=400)的原文用 ERR 前缀单独保留、
# 不参与滚动删除,方便复现商汤概率性 400 的根因。只落 body(Authorization 在 header,绝不落盘)。
# 不碰注入/轮换/冷却/重试业务逻辑,纯旁路写盘。
# env:
#   TTP_REQDUMP=0          # 关闭(默认开)
#   TTP_REQDUMP_DIR        # dump 目录(默认 trade-data/data/logs/sensenova-req-dump,仓外 gitignore)
#   TTP_REQDUMP_KEEP       # 非 ERR 保留最近 N 个(默认 30)
#   TTP_REQDUMP_KEEP_ERR   # ERR 保留最近 N 个(默认 30)
REQDUMP_ON = os.environ.get("TTP_REQDUMP", "1") == "1"
REQDUMP_DIR = os.environ.get("TTP_REQDUMP_DIR", "/Users/linhuichen/code/trade-data/data/logs/sensenova-req-dump")
REQDUMP_KEEP = int(os.environ.get("TTP_REQDUMP_KEEP", "30"))
REQDUMP_KEEP_ERR = int(os.environ.get("TTP_REQDUMP_KEEP_ERR", "30"))

def _reqdump_cleanup():
    """滚动清理:非 ERR 文件按 mtime 保留最近 KEEP 个,ERR 保留最近 KEEP_ERR 个,超出删除。
    ERR 文件(名含 ERR)不滚删 = 报错原文长期可查。文件名格式 req-<ts>-<hex>-<suffix>.json,
    suffix 为 REQ(未拿到 status 的半成品)/纯数字 status/ERR<status>。"""
    if not REQDUMP_ON:
        return
    try:
        _entries = os.listdir(REQDUMP_DIR)
    except FileNotFoundError:
        return
    _norm, _err = [], []
    for _e in _entries:
        if _e.startswith("req-") and _e.endswith(".json"):
            (_err if "ERR" in _e else _norm).append(_e)
    def _by_mtime_desc(names):
        _rows = []
        for _n in names:
            try:
                _rows.append((_n, os.path.getmtime(os.path.join(REQDUMP_DIR, _n))))
            except OSError:
                pass
        _rows.sort(key=lambda r: r[1], reverse=True)
        return [r[0] for r in _rows]
    for _keep, _group in ((REQDUMP_KEEP, _norm), (REQDUMP_KEEP_ERR, _err)):
        for _old in _by_mtime_desc(_group)[_keep:]:
            try:
                os.unlink(os.path.join(REQDUMP_DIR, _old))
            except OSError:
                pass

# ═══ 删 thinking(adaptive)绕过商汤推导超限(2026-09-01 重放定根因)═══
# 商汤 deepseek-v4-flash 端点对大上下文请求报
# "thinking_budget parameter must be a positive integer and not greater than 393216"
# 根因(重放铁证):thinking.type=adaptive 时商汤按上下文自推导 thinking_budget,大上下文下推导值
# 超 393216 上限 -> 400。之前注入 thinking_budget=32768 压不住(adaptive 用自己的推导值,不看传入)。
# 重放三组(ERR400 真原文,466KB/103msg 直连商汤):
#   ①留 adaptive -> 400/429  ②删 tb 留 adaptive -> 400(adaptive 仍自推导超限)
#   ③删 thinking 字段 -> 200 ✅(响应仍含 thinking content,思考能力不丢,只是不走 adaptive 自分配预算)
# 治本:删请求里的 thinking 字段(type=adaptive),让商汤走默认思考模式,不触发 adaptive 推导。
# 副效:adaptive 预留一大坨 thinking 预算是 tpm 大户,删了之后 tpm 消耗骤降,429 也跟着少。
# 从严条件:①content_type 含 json ②body 解析为 dict ③model 含 deepseek ④thinking.type==adaptive
# (非 adaptive 如 enabled 不动;glm/不带 thinking 的请求不动)。

def _strip_thinking_adaptive(body, content_type, path, req_headers):
    """删请求里的 thinking 字段(adaptive 模式),绕过商汤 adaptive 自推导 thinking_budget 超 393216 的 400。
    返回 (new_body_bytes, stripped: bool)。从严条件:
    ① content_type 含 json ② body 解析为 dict ③ model 含 deepseek(只 deepseek)
    ④ thinking.type == adaptive(非 adaptive 不动,保留 enabled 等其他模式原样转发)
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
    _tn = data.get("thinking")
    if not isinstance(_tn, dict) or _tn.get("type") != "adaptive":
        return body, False  # 非 adaptive 不动(glm/不带 thinking/enabled 等原样转发)
    data.pop("thinking", None)
    logmsg(f"STRIP thinking(adaptive) {path}")
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
        # 转发前删 thinking(adaptive)(绕过商汤 adaptive 自推导 thinking_budget 超限的 400,只对 deepseek adaptive 请求)
        body, _stripped = _strip_thinking_adaptive(body, self.headers.get("Content-Type", ""), self.path, self.headers)
        # 请求原文 dump(2026-09-01 用户定):落转发后字节逐字节原样(注入后=上游实际见到的),报错时抓完整原文。
        # 只落 body,不落 header(Authorization 在 header,key 严禁落盘);拿到 status 后再 rename 终态。
        self._reqdump_path = None
        if REQDUMP_ON and body:
            try:
                os.makedirs(REQDUMP_DIR, exist_ok=True)
                _ts = int(time.time())
                _hex = os.urandom(3).hex()
                _tmp = os.path.join(REQDUMP_DIR, f"req-{_ts}-{_hex}-REQ.json.tmp")
                with open(_tmp, "wb") as _f:
                    _f.write(body)
                _final = os.path.join(REQDUMP_DIR, f"req-{_ts}-{_hex}-REQ.json")
                os.replace(_tmp, _final)  # 原子写,防半截文件
                self._reqdump_path = _final
            except Exception:
                self._reqdump_path = None
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
                # 全部 key 冷却中(极端):保守整体退避(2026-09-01 用户拍板,B方案③保守版)。
                # 30s 起步递增等待,退避期间不发请求(不把 key 打进长冷却),到点重新探测
                # 是否有 key 恢复;累计超 8min 仍全冷却 → 如实返回 429。
                # ⚠️ 保守版,非容量判定:响应特征分不清容量 vs 配额,只做等待重试,不做断言。
                _wait = ALL_COOL_BACKOFF_L0
                _waited = 0
                while True:
                    # 等待前 cap 掉剩余累计额度:累计等待严格 ≤ ALL_COOL_BACKOFF_CAP(480s),
                    # 不会出现"单次 480s 把累计顶破到 900s"的情况(自测校正)。
                    _wait = min(_wait, ALL_COOL_BACKOFF_CAP - _waited)
                    time.sleep(_wait)
                    _waited += _wait
                    _recovered = []
                    for _ki in range(len(KEYS)):
                        if not _cooled_out(KEYS[_ki]):
                            _recovered.append((KEYS[_ki], KEY_NUMS[_ki]))
                    if _recovered:
                        try_keys = _recovered
                        logmsg(f"ALL COOL backoff recovered after {_waited:.0f}s, keys={len(_recovered)}")
                        break
                    if _waited >= ALL_COOL_BACKOFF_CAP:
                        logmsg("ALL KEYS COOLED (waited), return 429")
                        _b = b'{"type":"error","error":{"type":"rate_limit_error","message":"all keys cooling (quota exhausted)"}}'
                        self.send_response(429)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(_b)))
                        self.end_headers()
                        self.wfile.write(_b)
                        return
                    _wait = min(_wait * 2, ALL_COOL_BACKOFF_MAX)
        last = None
        for k, (key, key_num) in enumerate(try_keys):
            if k > 0 and ROTATE_BACKOFF > 0:
                time.sleep(_rotate_backoff())  # 换 key 重试前轻退避(高峰 1.5s/非高峰 0.3s),避免把多池全打满
            status, resp_body, resp_headers, resp_text, err = _do_upstream(
                self.command, upstream_path, body, self.headers, key)
            if err is not None:
                logmsg(f"UPSTREAM ERR {err}")
                self.send_response(502); self.end_headers(); self.wfile.write(str(err).encode()); return
            last = (status, resp_body, resp_headers, resp_text)
            # 成功/非限流响应 -> 清除该 key 冷却(额度恢复,下次额度型 429 重新从 180s 探)
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
        # 请求原文 dump 收尾:拿 status 后 rename 终态,>=400 用 ERR 前缀且不参与滚动删除
        if REQDUMP_ON and getattr(self, "_reqdump_path", None):
            try:
                _sfx = os.path.basename(self._reqdump_path).replace("req-", "").replace("-REQ.json", "")
                _final = os.path.join(REQDUMP_DIR,
                                      f"req-{_sfx}-{status}.json" if status < 400 else f"req-{_sfx}-ERR{status}.json")
                os.replace(self._reqdump_path, _final)
                logmsg(f"REQDUMP {os.path.basename(_final)}")
            except Exception:
                pass
            self._reqdump_path = None
            _reqdump_cleanup()
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
