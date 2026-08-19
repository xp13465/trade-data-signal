#!/usr/bin/env python3
"""
thinking_proxy.py - 本地代理:拦截 Claude Code 请求,对指定 model 注入 thinking:disabled

用途:Claude Code 对非Claude模型(glm/deepseek)永不发 {type:disabled}(ydr 阻断),
      导致默认 thinking ON 费 token。本代理在转发层强制注入 disabled,省 98% token。
      详见 docs/thinking-off-optimization.md §八(DeepSeek 官方直连实测)。

用法(常驻):
  TTP_INJECT=1 TTP_INJECT_MODELS=deepseek-v4-flash \
  TTP_UPSTREAM_HOST=api.deepseek.com TTP_UPSTREAM_PORT=443 TTP_UPSTREAM_BASE=/anthropic \
  python3 scripts/thinking_proxy.py
  监听 127.0.0.1:8899,转发到官方 DeepSeek Anthropic 兼容端点
  (默认即官方 api.deepseek.com/anthropic;火山兼容可切回 ark.cn-beijing.volces.com/api/coding)

激活步骤(已按 #32 启用):
  1. launchctl load scripts/com.trade.thinking-proxy.plist   # 守护代理
  2. settings.json env "ANTHROPIC_BASE_URL": "http://127.0.0.1:8899"(官方直连改走本地代理)
  3. .claude/agents/implementer.md + tester.md: model: deepseek-v4-flash(代理注入 disabled 省 token)
     reviewer/researcher/主控: model: deepseek-v4-think(flash 底别名,代理不注入 + 改写 flash = 保思考,零 v4-pro)

风险(P0):代理挂 = 全站 claude 不可用。launchd KeepAlive 守护 + claude 重试兜底。
回退:bash scripts/thinking-proxy-rollback.sh(还原 settings + unload + pkill,一键)。

env:
  TTP_INJECT=1                          # 开启注入
  TTP_INJECT_MODELS=deepseek-v4-flash   # 逗号分隔,匹配 model 字段子串;未匹配的 model 不注入(保思考)
  TTP_ALIAS_MODELS=deepseek-v4-think    # 判断类别名(flash 底保思考):不注入 + 改写 ALIAS_TARGET 转发
  TTP_ALIAS_TARGET=deepseek-v4-flash    # 别名改写成的真实 model(官方只认 pro/flash;别名直发 400/404)
  # 按需 thinking(2026-08-19 用户定,默认关+显式开):INJECT_MODELS 命中时默认注入 thinking:disabled 关思考;
  # 仅当请求显式带 {"thinking":{"type":"enabled"}} 时放行思考(不注入、不剥 effort)。adaptive 仍按默认关处理。
  TTP_PROVIDER=ark|official|ark-plan    # 快捷切换双端 upstream(优先,覆盖下面三个 TTP_UPSTREAM_*)
                                        #   ark      = 火山方舟  ark.cn-beijing.volces.com:443/api/coding
                                        #   ark-plan = 火山方舟 agent plan 端点 ark.cn-beijing.volces.com:443/api/plan
                                        #   official = 官方 DeepSeek api.deepseek.com:443/anthropic
  TTP_UPSTREAM_HOST/PORT/BASE           # 自定义 upstream(未设 TTP_PROVIDER 时用),默认官方
"""
import http.server, json, http.client, threading, time, sys, ssl, re, os

LOG = os.environ.get("TTP_LOG", "/Users/linhuichen/code/trade-data/data/logs/thinking-proxy-req.log")
# upstream 配置化。默认官方 DeepSeek Anthropic 兼容端点;火山兼容:host=ark.cn-beijing.volces.com base=/api/coding。
# TTP_PROVIDER=ark|official|ark-plan 快捷切换双端(2026-08-14 加,一套脚本眷顾官方/火山;2026-08-16 加 ark-plan agent plan 端点)。
PROVIDER = os.environ.get("TTP_PROVIDER", "")
PROVIDERS = {
    # 官方 DeepSeek Anthropic 兼容端点(2026-08-14 实测仍可用,disabled 真关)
    "official": {"host": "api.deepseek.com", "port": 443, "base": "/anthropic"},
    # 火山方舟 coding 端点(2026-08-14 实测 disabled 真关/别名直发 404)
    "ark": {"host": "ark.cn-beijing.volces.com", "port": 443, "base": "/api/coding"},
    # 火山方舟 agent plan 端点(现网,2026-08-16 切换;agent plan 不认 think 名,走代理 think→flash 改写)
    "ark-plan": {"host": "ark.cn-beijing.volces.com", "port": 443, "base": "/api/plan"},
}
if PROVIDER in PROVIDERS:
    UPSTREAM_HOST = PROVIDERS[PROVIDER]["host"]
    UPSTREAM_PORT = PROVIDERS[PROVIDER]["port"]
    UPSTREAM_BASE = PROVIDERS[PROVIDER]["base"]
else:
    UPSTREAM_HOST = os.environ.get("TTP_UPSTREAM_HOST", "api.deepseek.com")
    UPSTREAM_PORT = int(os.environ.get("TTP_UPSTREAM_PORT", "443"))
    UPSTREAM_BASE = os.environ.get("TTP_UPSTREAM_BASE", "/anthropic")
SSL_CTX = ssl._create_unverified_context()  # 本地代理,跳过证书验证(转发到已知 upstream)
INJECT = os.environ.get("TTP_INJECT", "") == "1"
INJECT_MODELS = [m for m in os.environ.get("TTP_INJECT_MODELS", "deepseek-v4-flash").split(",") if m]
# 判断类别名(flash 底保思考):请求体 model 匹配任一别名时,不注入 disabled(保 thinking),
# 但把 model 改写成官方认可的真实 flash 再转发(官方只认 deepseek-v4-pro/flash 两个名,别名直发会 400)。
# 作用:让判断类(reviewer/researcher/主控)frontmatter 用别名,代理据此区分角色——别名=保思考、flash=注入关思考。
ALIAS_MODELS = [m for m in os.environ.get("TTP_ALIAS_MODELS", "deepseek-v4-think").split(",") if m]
ALIAS_TARGET = os.environ.get("TTP_ALIAS_TARGET", "deepseek-v4-flash")  # 别名改写成的真实模型名(底层能力)

def logmsg(s):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {s}\n")
    print(s, flush=True)

class Handler(http.server.BaseHTTPRequestHandler):
    def _forward(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        thinking_field = None; model_field = None; obj = None
        is_message_post = (self.command == "POST") and ("/v1/messages" in self.path or "/messages" in self.path)
        if is_message_post and length:
            try:
                obj = json.loads(body)
                model_field = obj.get("model")
                thinking_field = obj.get("thinking", "<OMITTED>")
            except Exception as e:
                thinking_field = f"<parse-error {e}>"
        # ═══ 固定模型铁律(2026-08-15 用户定,从"堵 v4-pro 泄漏"升级为核心原则)═══
        # 白名单 = INJECT_MODELS(flash,注入关思考)+ ALIAS_MODELS(think,别名保思考改写 flash)。
        # 之外任何 model(无论 v4-pro / claude-opus-5 / 未来新模型名 / 缺 model)一律不放行:
        # 默认改写 ALIAS_TARGET(flash)+ 告警日志,绝不透传。只有闪 flash 注入、think 别名两种
        # 是用户要求的模型,其余都不是"我要求让你用的模型"。
        # 拒绝 vs 改写:默认改写 flash(保留功能成本回落到 flash);改写序列化失败则拒绝不转发。
        injected = False
        aliased = False
        fallback = False
        explicit_thinking = False
        if is_message_post and length and obj is not None and model_field is not None:
            # GET/静态请求不解析不清除(is_message_post=False),不会走到这里
            if any(m in str(model_field) for m in INJECT_MODELS) and INJECT:
                # 按需 thinking(2026-08-19 用户定,默认关+显式开):默认注入 disabled 关思考省 token;
                # 仅当请求显式带 {"thinking":{"type":"enabled"}} 时放行思考(按需开),不注入、不剥 effort。
                # adaptive(Claude Code 默认对 deepseek 发的)≠enabled,仍按默认关处理(adaptive 在方舟=ON 最费)。
                _t = obj.get("thinking")
                _explicit_enabled = isinstance(_t, dict) and _t.get("type") == "enabled"
                if not _explicit_enabled:
                    obj["thinking"] = {"type": "disabled"}
                    injected = True
                    # 2026-08-17 fix: DeepSeek 官方对 thinking disabled 不接受 reasoning_effort
                    # (报 400 Invalid combination high+disabled)。Claude Code 会话 CLAUDE_EFFORT=high 会
                    # 透传为 reasoning_effort,flash(注入 disabled)必须剥离,否则 implementer/tester 一启动
                    # 就 400。think 请求(aliased)不 injected,不剥离,不受影响。
                    if "reasoning_effort" in obj:
                        _re = obj.pop("reasoning_effort")
                        logmsg(f"strip reasoning_effort={_re} for injected flash(thinking disabled, 400 fix)")
                    # 2026-08-17 fix2: Claude Code 新版把 effort 放 output_config.effort(非顶层 reasoning_effort),
                    # DeepSeek 兼容层映射成 reasoning_effort=high 遇 disabled 报 400。实测 agent 请求
                    # output_config={"effort":"high"} 顶层无 reasoning_effort。剥离 + 空则删整个。
                    _oc = obj.get("output_config")
                    if isinstance(_oc, dict):
                        _ce = _oc.pop("effort", None)
                        if _ce is not None:
                            logmsg(f"strip output_config.effort={_ce} for injected flash(thinking disabled, 400 fix)")
                        if not _oc:
                            obj.pop("output_config", None)
                else:
                    explicit_thinking = True
                    logmsg("ONDEMAND 显式 thinking enabled,放行思考(不注入 disabled)")
            elif any(m in str(model_field) for m in ALIAS_MODELS):
                obj["model"] = ALIAS_TARGET
                aliased = True
            else:
                obj["model"] = ALIAS_TARGET
                fallback = True
                logmsg(f"WARN 未知model兜底改写 model={model_field}->{ALIAS_TARGET}")
        elif is_message_post and length and obj is not None and model_field is None:
            # POST 消息请求却无 model 字段(<parse-error 之外无 model>)= 异常,同兜底处理
            obj["model"] = ALIAS_TARGET
            fallback = True
            logmsg("WARN 未知model兜底改写 model=None(缺 model 字段)->" + ALIAS_TARGET)
        if injected or aliased or fallback:
            try:
                body = json.dumps(obj).encode()
            except Exception as e:
                # 改写失败 → 拒绝转发,绝不透传原样(原样=泄漏),返回 502
                logmsg(f"CRIT 未知model兜底改写失败,拒绝转发 model={model_field} err={e}")
                self.send_response(502); self.end_headers()
                self.wfile.write(f"model rewrite failed, refusing to forward".encode())
                return
        logmsg(f"REQ {self.command} {self.path} model={model_field}->{obj.get('model') if obj else None} thinking={json.dumps(thinking_field, ensure_ascii=False) if thinking_field is not None else None} injected={injected} aliased={aliased} fallback={fallback} explicit={explicit_thinking}")
        conn = http.client.HTTPSConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=180, context=SSL_CTX)
        upstream_path = UPSTREAM_BASE + self.path
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
        headers["Host"] = UPSTREAM_HOST
        try:
            conn.request(self.command, upstream_path, body=body, headers=headers)
            resp = conn.getresponse()
            resp_body = resp.read()
        except Exception as e:
            logmsg(f"UPSTREAM ERR {e}")
            self.send_response(502); self.end_headers(); self.wfile.write(str(e).encode()); return
        resp_text = resp_body.decode('utf-8', 'replace')
        outs = re.findall(r'"output_tokens"\s*:\s*(\d+)', resp_text)
        out_tok = outs[-1] if outs else "?"
        has_think = ('"type":"thinking"' in resp_text) or ('"type": "thinking"' in resp_text)
        # 记录完整 usage(input/output/cache/thinking)做 token 审计(2026-08-14 加,A/B 对照需 input 侧)。
        # 兼容流式(SSE):usage 在最后一个 event: message_stop 的 data JSON 里,不是整个 body 单个 JSON。
        uin = uout = ucc = ucr = uth = "?"
        try:
            if resp_text.lstrip().startswith("event:"):
                # SSE:遍历每个 "data: {...}" 块,取最后一个含 usage 的 message_stop
                for chunk in resp_text.split("\n\n"):
                    if "data:" not in chunk:
                        continue
                    dline = chunk.split("data:", 1)[1].strip()
                    try:
                        ev = json.loads(dline)
                    except Exception:
                        continue
                    if ev.get("type") == "message_stop" and ev.get("usage"):
                        u = ev["usage"]; break
                    elif ev.get("usage"):
                        u = ev["usage"]; break
                else:
                    u = {}
                uin = u.get("input_tokens", "?"); uout = u.get("output_tokens", "?")
                ucc = u.get("cache_creation_input_tokens", 0); ucr = u.get("cache_read_input_tokens", 0)
                uth = u.get("thinking_tokens", 0)
            else:
                u = json.loads(resp_text).get("usage", {})
                uin = u.get("input_tokens", "?"); uout = u.get("output_tokens", "?")
                ucc = u.get("cache_creation_input_tokens", 0); ucr = u.get("cache_read_input_tokens", 0)
                uth = u.get("thinking_tokens", 0)
        except Exception:
            pass
        logmsg(f"RESP {resp.status} bytes={len(resp_body)} has_thinking={has_think} "
               f"usage(in={uin} out={uout} cc={ucc} cr={ucr} think={uth})")
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("transfer-encoding", "connection", "content-length"): continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)
        conn.close()
    def do_POST(self): self._forward()
    def do_GET(self): self._forward()
    def do_PUT(self): self._forward()
    def do_DELETE(self): self._forward()
    def do_OPTIONS(self): self._forward()
    def log_message(self, *a): pass

if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8899), Handler)
    logmsg(f"proxy listening on 127.0.0.1:8899 provider={PROVIDER or UPSTREAM_HOST} INJECT={INJECT} MODELS={INJECT_MODELS} ALIAS_MODELS={ALIAS_MODELS}->{ALIAS_TARGET} -> https://{UPSTREAM_HOST}{UPSTREAM_BASE}")
    server.serve_forever()
