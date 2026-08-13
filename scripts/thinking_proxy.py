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
     reviewer/researcher/主控: model: deepseek-v4-pro(代理不注入 = 保思考)

风险(P0):代理挂 = 全站 claude 不可用。launchd KeepAlive 守护 + claude 重试兜底。
回退:bash scripts/thinking-proxy-rollback.sh(还原 settings + unload + pkill,一键)。

env:
  TTP_INJECT=1                          # 开启注入
  TTP_INJECT_MODELS=deepseek-v4-flash   # 逗号分隔,匹配 model 字段子串;未匹配的 model 不注入(保思考)
  TTP_UPSTREAM_HOST/PORT/BASE           # upstream 配置,默认官方 api.deepseek.com:443/anthropic
"""
import http.server, json, http.client, threading, time, sys, ssl, re, os

LOG = os.environ.get("TTP_LOG", "/Users/linhuichen/code/trade-data/data/logs/thinking-proxy-req.log")
# upstream 配置化(默认官方 DeepSeek Anthropic 兼容端点;火山兼容:host=ark.cn-beijing.volces.com base=/api/coding)
UPSTREAM_HOST = os.environ.get("TTP_UPSTREAM_HOST", "api.deepseek.com")
UPSTREAM_PORT = int(os.environ.get("TTP_UPSTREAM_PORT", "443"))
UPSTREAM_BASE = os.environ.get("TTP_UPSTREAM_BASE", "/anthropic")
SSL_CTX = ssl._create_unverified_context()  # 本地代理,跳过证书验证(转发到已知 upstream)
INJECT = os.environ.get("TTP_INJECT", "") == "1"
INJECT_MODELS = [m for m in os.environ.get("TTP_INJECT_MODELS", "deepseek-v4-flash").split(",") if m]

def logmsg(s):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {s}\n")
    print(s, flush=True)

class Handler(http.server.BaseHTTPRequestHandler):
    def _forward(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        thinking_field = None; model_field = None
        try:
            obj = json.loads(body)
            model_field = obj.get("model")
            thinking_field = obj.get("thinking", "<OMITTED>")
        except Exception as e:
            thinking_field = f"<parse-error {e}>"
        # 注入 disabled(只对指定 model)
        injected = False
        if INJECT and model_field and any(m in str(model_field) for m in INJECT_MODELS):
            obj["thinking"] = {"type": "disabled"}
            body = json.dumps(obj).encode()
            injected = True
        logmsg(f"REQ {self.command} {self.path} model={model_field} thinking={json.dumps(thinking_field, ensure_ascii=False)} injected={injected}")
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
        logmsg(f"RESP {resp.status} bytes={len(resp_body)} has_thinking={has_think} output={out_tok}")
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
    logmsg(f"proxy listening on 127.0.0.1:8899 INJECT={INJECT} MODELS={INJECT_MODELS} -> https://{UPSTREAM_HOST}{UPSTREAM_BASE}")
    server.serve_forever()
